"""本地双人热座（PvP）集成测试：两个座位都由真人操作。

覆盖：创建（含第二座位先手时的"直接交回合"）、视角隔手牌、两位玩家交替操作、
真人防守的响应挂起（AI 不再当场定夺）、seat 校验、中性结果文案。
人机模式的回归由既有的 test_api / test_battle / 契约测试负责。
"""

import random

import pytest

from app import create_app
from game.battle import BattleState
from game.models import Side
from game.session_state import save_battle


def make_client(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DATABASE": str(tmp_path / "pvp.sqlite3"),
        }
    )
    return app.test_client()


def install_pvp(client, *, starting_side=Side.PLAYER, seed=7):
    """把一局确定性的双人对局写进 session（战士 vs 法师）。"""
    with client.session_transaction() as session:
        save_battle(
            session,
            BattleState.create(
                "warrior",
                random.Random(seed),
                starting_side=starting_side,
                mode="pvp",
                opponent_hero_key="mage",
            ),
        )
        session.modified = True


def side_state(session, side):
    return session["battle"]["participants"][side]


def get_state(client, seat=None):
    suffix = f"?seat={seat}" if seat else ""
    return client.get(f"/api/game{suffix}").get_json()["data"]


def freeze_hands(client, *, player_hand, enemy_hand, player_energy, enemy_energy):
    """锁死双方手牌与能量：补牌区清空后回合开始就抽不到东西，断言才确定。"""
    with client.session_transaction() as session:
        for side, hand, energy in (
            ("player", player_hand, player_energy),
            ("enemy", enemy_hand, enemy_energy),
        ):
            state = side_state(session, side)
            state["hand"] = hand
            state["draw_pile"] = []
            state["discard_pile"] = []
            state["combatant"]["energy"] = energy
        enemy = side_state(session, "enemy")
        enemy["combatant"]["shield"] = 0
        enemy["armor"] = None
        session.modified = True


def test_pvp_create_via_api_exposes_mode_and_runs_no_ai(tmp_path):
    client = make_client(tmp_path)

    response = client.post(
        "/api/game",
        json={"mode": "pvp", "hero_key": "warrior", "opponent_hero_key": "mage"},
    )

    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["mode"] == "pvp"
    assert data["viewer"] == "player"
    assert data["enemy"]["hero"]["key"] == "mage"
    # 双人模式没有电脑席位：先手是谁就停在谁的回合，绝不出现服务端跑回合。
    assert data["phase"] in {"PLAYER_TURN", "ENEMY_TURN"}
    assert not any("电脑" in line for line in data["log"])
    # 契约字段仍然恒在（双人下无实际作用，前端可忽略）。
    assert data["ai_difficulty"] in {"easy", "medium", "hard"}


def test_pvp_second_seat_start_hands_the_turn_over_instead_of_running_ai(tmp_path):
    client = make_client(tmp_path)
    install_pvp(client, starting_side=Side.ENEMY)

    state = get_state(client)

    assert state["phase"] == "ENEMY_TURN"
    assert state["starting_side"] == "enemy"
    assert state["viewer"] == "player"
    assert state["player"]["energy"] == 3  # 玩家1 是后手：正常 3 点
    # 玩家2 的资源原样等待本人操作：先手方第 1 回合只有 2 点能量，手牌 5 张。
    enemy_view = get_state(client, seat="enemy")
    assert enemy_view["viewer"] == "enemy"
    assert len(enemy_view["enemy"]["hand"]) == 5
    assert enemy_view["enemy"]["energy"] == 2
    assert enemy_view["available_actions"]["end_turn"] is True
    assert not any("电脑" in line for line in state["log"])


def test_pvp_viewer_hand_visibility_switches_with_seat(tmp_path):
    client = make_client(tmp_path)
    install_pvp(client)

    first = get_state(client, seat="player")
    second = get_state(client, seat="enemy")

    assert first["viewer"] == "player"
    assert "hand" in first["player"]
    assert "hand" not in first["enemy"]
    assert second["viewer"] == "enemy"
    assert "hand" in second["enemy"]
    assert "hand" not in second["player"]
    # 两份视角说的是同一局：公开资源完全一致。
    assert first["player"]["hp"] == second["player"]["hp"]
    assert first["enemy"]["hero"] == second["enemy"]["hero"]
    assert first["round_number"] == second["round_number"]


def test_pvp_turns_alternate_between_the_two_real_players(tmp_path):
    client = make_client(tmp_path)
    install_pvp(client)
    freeze_hands(
        client,
        player_hand=[{"id": "p1-slash", "key": "slash"}],
        enemy_hand=[{"id": "p2-heavy", "key": "heavy_strike"}],
        player_energy=3,
        enemy_energy=3,
    )

    # 玩家1 出牌打脸 → 结束回合，交棒给玩家2。
    hp_before = get_state(client).get("enemy", {}).get("hp")
    after_card = client.post(
        "/api/game/actions/card", json={"seat": "player", "card_id": "p1-slash"}
    ).get_json()["data"]
    assert after_card["enemy"]["hp"] == hp_before - 6

    ended = client.post("/api/game/actions/end-turn", json={"seat": "player"})
    assert ended.status_code == 200
    assert ended.get_json()["data"]["phase"] == "ENEMY_TURN"

    # 电脑不在场：玩家2 的手牌没有被任何 AI 动作碰过，等待本人操作。
    enemy_view = get_state(client, seat="enemy")
    assert len(enemy_view["enemy"]["hand"]) == 1
    assert enemy_view["available_actions"]["play_card"] is True

    # 玩家2 出牌 → 结束回合，回到玩家1。
    player_hp_before = get_state(client).get("player", {}).get("hp")
    after_enemy_card = client.post(
        "/api/game/actions/card", json={"seat": "enemy", "card_id": "p2-heavy"}
    ).get_json()["data"]
    assert after_enemy_card["player"]["hp"] == player_hp_before - 10

    back_to_one = client.post(
        "/api/game/actions/end-turn", json={"seat": "enemy"}
    ).get_json()["data"]
    assert back_to_one["phase"] == "PLAYER_TURN"
    assert back_to_one["round_number"] == 2
    assert back_to_one["viewer"] == "enemy"
    assert not any("电脑" in line for line in back_to_one["log"])


def test_pvp_enemy_attack_waits_for_the_real_defender(tmp_path):
    client = make_client(tmp_path)
    install_pvp(client)
    freeze_hands(
        client,
        player_hand=[{"id": "p1-slash", "key": "slash"}],
        enemy_hand=[{"id": "p2-dodge", "key": "dodge"}],
        player_energy=3,
        enemy_energy=2,
    )

    # 玩家1 攻击玩家2：玩家2 手里有闪避 → 挂起等比人响应（AI 不再当场定夺）。
    paused = client.post(
        "/api/game/actions/card", json={"seat": "player", "card_id": "p1-slash"}
    ).get_json()["data"]
    assert paused["phase"] == "RESPONSE"
    # 攻击方视角：不用自己响应，但看得到挂起的公开信息。
    assert paused["response"]["active"] is False
    assert paused["response"]["attacker"] == "player"
    assert paused["response"]["card_name"] == "斩击"
    assert paused["response"]["damage"] == 6

    # 防守方视角：轮到本人决定。
    defender_view = get_state(client, seat="enemy")
    assert defender_view["response"]["active"] is True
    assert defender_view["available_actions"]["respond"] == {
        "dodge": True,
        "negate": False,
        "pass": True,
    }
    hp_before = defender_view["enemy"]["hp"]

    # 玩家2 自己决定闪避，回合交还玩家1。
    dodged = client.post(
        "/api/game/actions/respond", json={"seat": "enemy", "action": "dodge"}
    ).get_json()["data"]
    assert dodged["phase"] == "PLAYER_TURN"
    assert dodged["enemy"]["hp"] == hp_before
    assert "玩家1使用【斩击】" in dodged["log"]
    assert "玩家2使用【闪避】，抵消了本次伤害" in dodged["log"]


def test_pvp_second_players_attack_keeps_the_turn_with_a_human_after_a_pass(tmp_path):
    """玩家2 攻击玩家1、玩家1 放弃响应后：回合留在玩家2 手里，AI 不得接管。

    这条覆盖一个真实漏洞（复核 R-01）：响应收尾路径原本按"攻击方是不是 ENEMY"
    决定要不要跑电脑行动，双人模式下会把玩家2 的回合交给 AI 打完。
    """
    client = make_client(tmp_path)
    install_pvp(client, starting_side=Side.ENEMY)
    freeze_hands(
        client,
        player_hand=[{"id": "p1-dodge", "key": "dodge"}],
        enemy_hand=[{"id": "p2-heavy", "key": "heavy_strike"}],
        player_energy=3,
        enemy_energy=3,
    )

    # 玩家2 打重击（2 费）→ 玩家1 手里有闪避 → 挂起等玩家1。
    paused = client.post(
        "/api/game/actions/card", json={"seat": "enemy", "card_id": "p2-heavy"}
    ).get_json()["data"]
    assert paused["phase"] == "RESPONSE"
    assert paused["response"]["active"] is False  # 攻击方视角
    assert paused["response"]["attacker"] == "enemy"
    player_view = get_state(client)
    assert player_view["response"]["active"] is True

    hp_before = player_view["player"]["hp"]
    # 玩家1 放弃响应：伤害落地，回合仍在玩家2 手里等本人继续。
    passed = client.post(
        "/api/game/actions/respond", json={"seat": "player", "action": "pass"}
    ).get_json()["data"]
    assert passed["phase"] == "ENEMY_TURN"
    assert passed["player"]["hp"] == hp_before - 10

    # 电脑没有替玩家2 打过任何一张牌：能量停在出牌后的 1 点，手牌为空，日志无"电脑"。
    enemy_view = get_state(client, seat="enemy")
    assert enemy_view["enemy"]["energy"] == 1
    assert enemy_view["enemy"]["hand"] == []
    assert enemy_view["available_actions"]["end_turn"] is True
    assert not any("电脑" in line for line in passed["log"])

    # 玩家2 本人结束回合，正常交回玩家1。
    back = client.post(
        "/api/game/actions/end-turn", json={"seat": "enemy"}
    ).get_json()["data"]
    assert back["phase"] == "PLAYER_TURN"


def test_pvp_second_players_attack_keeps_the_turn_with_a_human_after_a_dodge(tmp_path):
    """同上，但玩家1 用闪避响应：伤害被抵消，回合依旧留在玩家2。"""
    client = make_client(tmp_path)
    install_pvp(client, starting_side=Side.ENEMY)
    freeze_hands(
        client,
        player_hand=[{"id": "p1-dodge", "key": "dodge"}],
        enemy_hand=[{"id": "p2-heavy", "key": "heavy_strike"}],
        player_energy=3,
        enemy_energy=3,
    )

    client.post("/api/game/actions/card", json={"seat": "enemy", "card_id": "p2-heavy"})
    hp_before = get_state(client)["player"]["hp"]
    dodged = client.post(
        "/api/game/actions/respond", json={"seat": "player", "action": "dodge"}
    ).get_json()["data"]

    assert dodged["phase"] == "ENEMY_TURN"
    assert dodged["player"]["hp"] == hp_before
    assert dodged["player"]["energy"] == 2  # 玩家1 付了闪避的 1 费
    enemy_view = get_state(client, seat="enemy")
    assert enemy_view["enemy"]["energy"] == 1  # 电脑没有替玩家2 继续行动
    assert "玩家1使用【闪避】，抵消了本次伤害" in dodged["log"]


def test_pvp_result_copy_is_neutral_for_both_readers(tmp_path):
    client = make_client(tmp_path)
    install_pvp(client, starting_side=Side.ENEMY)
    with client.session_transaction() as session:
        battle = session["battle"]
        battle["phase"] = "PLAYER_TURN"
        battle["round_number"] = 10
        battle["participants"]["player"]["combatant"]["hp"] = 24
        battle["participants"]["enemy"]["combatant"]["hp"] = 20
        session.modified = True

    data = client.post(
        "/api/game/actions/end-turn", json={"seat": "player"}
    ).get_json()["data"]

    assert data["phase"] == "VICTORY"
    assert data["result"]["reason"] == "hp"
    # 共享的结果文案必须中性：两边读同一份，不能出现"你 / 电脑"。
    assert "玩家1" in data["result"]["text"]
    assert "你" not in data["result"]["text"]
    assert "电脑" not in data["result"]["text"]


def test_battle_state_rejects_an_unknown_mode_and_tolerates_a_bad_archive(tmp_path):
    """模型层防御：拼错 mode 当场抛错；被改坏的存档按人机模式容错读出。"""
    with pytest.raises(ValueError):
        BattleState.create("warrior", random.Random(7), mode="coop")

    good = BattleState.create("warrior", random.Random(7))
    payload = good.to_dict()
    payload["mode"] = "coop"
    fallback = BattleState.from_dict(payload)
    assert fallback.mode == "pve"


def test_pvp_seat_errors_and_turn_ownership(tmp_path):
    client = make_client(tmp_path)
    # 人机模式：enemy 座位由电脑操作，请求方不能替它行动。
    with client.session_transaction() as session:
        save_battle(
            session,
            BattleState.create("warrior", random.Random(7), starting_side=Side.PLAYER),
        )
        session.modified = True
    ai_seat = client.post("/api/game/actions/end-turn", json={"seat": "enemy"})
    assert ai_seat.status_code == 400
    assert ai_seat.get_json()["error"]["code"] == "INVALID_SEAT"

    bad_value = client.post("/api/game/actions/end-turn", json={"seat": "seat9"})
    assert bad_value.status_code == 400
    assert bad_value.get_json()["error"]["code"] == "INVALID_SEAT"

    # 双人模式：轮到玩家1 时，玩家2 的操作请求会被战斗规则拒绝。
    install_pvp(client)
    wrong_turn = client.post("/api/game/actions/end-turn", json={"seat": "enemy"})
    assert wrong_turn.status_code == 422
    assert wrong_turn.get_json()["error"]["code"] == "ACTION_REJECTED"
    assert wrong_turn.get_json()["error"]["message"] == "现在不是你的回合"
