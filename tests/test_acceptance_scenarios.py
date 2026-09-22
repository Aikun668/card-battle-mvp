"""End-to-end acceptance scenarios mirroring docs/claude-builder/acceptance.md §6.

A single linear test exercises the eleven manual scenarios in order so they
share the same Flask session. We use the test client because urllib cannot
reliably preserve Flask flash state across POST→302→GET.
"""

import json
import os
import sqlite3
import sys
import tempfile

from game.catalog import HEROES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def side_state(session: dict, side: str) -> dict:
    """读取 session 里某个参与者的原始分区。"""
    return session["battle"]["participants"][side]


def drop_enemy_dodge(session: dict) -> None:
    """电脑手里有闪避就能响应玩家的攻击，这里要验证的是伤害当场落地。"""
    enemy = side_state(session, "enemy")
    enemy["hand"] = [card for card in enemy["hand"] if card["key"] != "dodge"]


def test_acceptance_walk_through():
    from app import create_app  # noqa: PLC0415

    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "scenario.sqlite3")
    app = create_app({"TESTING": True, "SECRET_KEY": "s", "DATABASE": db})
    client = app.test_client()

    # Scenario 1 — start flow lists three heroes
    assert client.get("/demo").status_code == 200
    body = client.get("/demo/heroes").get_data(as_text=True)
    for name in ("战士", "法师", "游侠"):
        assert name in body

    # Scenario 2 — confirm button disabled before selection
    assert "确认角色" in body and "hero-card" in body

    # Scenario 3 — selecting a hero creates a battle with full state
    r = client.post("/demo/heroes", data={"hero_key": "warrior"}, follow_redirects=True)
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    for needle in ("生命值", "护盾", "能量", "结束回合", "战斗日志", "当前回合"):
        assert needle in body
    with client.session_transaction() as s:
        player = side_state(s, "player")
        enemy = side_state(s, "enemy")
        # 先手方由 RNG 决定；电脑先手时它的第一个回合在创建流程里推到
        # 需要玩家决定的点为止：玩家回合，或停在响应窗口等玩家响应。
        assert s["battle"]["phase"] in ("PLAYER_TURN", "RESPONSE")
        assert s["battle"]["starting_side"] in ("player", "enemy")
        if s["battle"]["starting_side"] == "enemy":
            if s["battle"]["phase"] == "RESPONSE":
                assert s["battle"]["pending_attack"]["defender"] == "player"
            else:
                # 电脑先手时开局那一手可能是普通牌，也可能是英雄技能。
                assert any(
                    e.startswith(("电脑使用", "电脑释放技能"))
                    for e in s["battle"]["log"]
                )
        assert 0 < player["combatant"]["hp"] <= player["combatant"]["max_hp"]
        assert enemy["hero_key"] in HEROES
        assert enemy["combatant"]["hp"] == enemy["combatant"]["max_hp"]
        assert player["combatant"]["energy"] == 3
        assert len(player["hand"]) == 5

    # 停在响应窗口时逐次放弃，把行动权交回玩家（场景 4 需要玩家回合）。
    # 电脑一个回合可能打出多张攻击，响应窗口会连续出现。
    for _ in range(5):
        with client.session_transaction() as s:
            response_pending = s["battle"]["phase"] == "RESPONSE"
        if not response_pending:
            break
        client.post("/demo/battle/respond", data={"action": "pass"})

    # Scenario 4 — normal card play
    with client.session_transaction() as s:
        side_state(s, "player")["hand"] = [{"id": "p-s", "key": "slash"}]
        enemy = side_state(s, "enemy")
        # 电脑先手时可能已经叠过护盾、装上铁甲，先清掉才能验证伤害。
        enemy["combatant"]["shield"] = 0
        enemy["armor"] = None
        drop_enemy_dodge(s)
        enemy_hp_before = enemy["combatant"]["hp"]
        s.modified = True
    client.post("/demo/battle/card/p-s", follow_redirects=True)
    with client.session_transaction() as s:
        assert side_state(s, "enemy")["combatant"]["hp"] == enemy_hp_before - 6
        assert side_state(s, "player")["combatant"]["energy"] == 2
        assert side_state(s, "player")["hand"] == []
        assert any("斩击" in e for e in s["battle"]["log"])

    # Scenario 5 — insufficient energy flash, state unchanged
    with client.session_transaction() as s:
        player = side_state(s, "player")
        player["combatant"]["energy"] = 0
        player["hand"] = [{"id": "p-fb", "key": "fireball"}]
        enemy_hp_before = side_state(s, "enemy")["combatant"]["hp"]
        s.modified = True
    r = client.post("/demo/battle/card/p-fb", follow_redirects=True)
    assert "能量不足" in r.get_data(as_text=True)
    with client.session_transaction() as s:
        assert side_state(s, "player")["combatant"]["energy"] == 0
        assert side_state(s, "enemy")["combatant"]["hp"] == enemy_hp_before
        assert side_state(s, "player")["hand"][0]["id"] == "p-fb"

    # Scenario 6 — skill limit per turn
    with client.session_transaction() as s:
        player = side_state(s, "player")
        player["combatant"]["energy"] = 3
        player["combatant"]["shield"] = 0
        player["skill_used_this_turn"] = False
        s.modified = True
    client.post("/demo/battle/skill", follow_redirects=True)
    with client.session_transaction() as s:
        first_shield = side_state(s, "player")["combatant"]["shield"]
    r = client.post("/demo/battle/skill", follow_redirects=True)
    assert "本回合技能已经使用过" in r.get_data(as_text=True)
    with client.session_transaction() as s:
        assert side_state(s, "player")["combatant"]["shield"] == first_shield

    # Scenario 7 — end-turn runs the enemy turn until nothing is worth playing
    with client.session_transaction() as s:
        s["battle"]["round_number"] = 1
        player = side_state(s, "player")
        enemy = side_state(s, "enemy")
        # 电脑也能用英雄技能了。把它固定成满血战士（8 点护盾技能，评分 8 低于斩击的 9），
        # 中等难度取分数最高的两个候选时它永远进不了池子，出牌顺序只由这三张斩击决定。
        # 一旦电脑掉血，风险系数会把护盾技能抬到斩击之上，这里就不能再固定顺序了。
        enemy["hero_key"] = "warrior"
        enemy["combatant"]["max_hp"] = 32
        enemy["combatant"]["hp"] = 32
        enemy["hand"] = [
            {"id": "e-s1", "key": "slash"},
            {"id": "e-s2", "key": "slash"},
            {"id": "e-s3", "key": "slash"},
        ]
        # 清空电脑的牌区，它这一回合就补不到新牌，手牌固定为上面三张。
        enemy["draw_pile"] = []
        enemy["discard_pile"] = []
        enemy["combatant"]["shield"] = 0
        player["combatant"]["shield"] = 0
        player["combatant"]["hp"] = 32
        s["battle"]["log"] = []
        s.modified = True
    client.post("/demo/battle/end-turn", follow_redirects=True)
    with client.session_transaction() as s:
        # 电脑每打完一张牌都重新评分，3 点能量正好连出三张斩击。
        assert (
            sum(1 for entry in s["battle"]["log"] if entry.startswith("电脑使用")) == 3
        )
        assert side_state(s, "player")["combatant"]["hp"] == 14
        assert side_state(s, "enemy")["combatant"]["energy"] == 0
        assert s["battle"]["phase"] == "PLAYER_TURN"
        assert s["battle"]["round_number"] == 2
        assert side_state(s, "player")["combatant"]["energy"] == 3

    # Scenario 8 — page refresh does not re-trigger the last action
    state_before = None
    with client.session_transaction() as s:
        state_before = json.dumps(s["battle"], sort_keys=True)
    client.get("/demo/battle")
    client.get("/demo/battle")
    with client.session_transaction() as s:
        state_after = json.dumps(s["battle"], sort_keys=True)
    assert state_before == state_after

    # Scenario 9 — terminal state blocks further actions, writes one row
    with client.session_transaction() as s:
        enemy = side_state(s, "enemy")
        enemy["combatant"]["hp"] = 1
        enemy["combatant"]["shield"] = 0
        drop_enemy_dodge(s)
        side_state(s, "player")["hand"] = [{"id": "p-kill", "key": "slash"}]
        s["battle"]["phase"] = "PLAYER_TURN"
        s.modified = True
    r = client.post("/demo/battle/card/p-kill", follow_redirects=True)
    battle_body = r.get_data(as_text=True)
    # The /battle page should now be in VICTORY phase with action buttons disabled
    assert "查看结果" in battle_body or "再来一局" in battle_body
    with client.session_transaction() as s:
        assert s["battle"]["phase"] == "VICTORY"
    # Following the result link shows the result page
    result_body = client.get("/demo/result").get_data(as_text=True)
    assert "胜利" in result_body or "再来一局" in result_body
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM match_results").fetchone()[0] == 1

    # Scenario 10 — restart clears state and returns to hero selection
    r = client.post("/demo/restart", follow_redirects=True)
    assert r.status_code == 200
    assert "确认角色" in r.get_data(as_text=True)
    with client.session_transaction() as s:
        assert "battle" not in s
    r2 = client.get("/demo/battle")
    assert r2.status_code == 302
    assert r2.headers["Location"].endswith("/demo/heroes")

    # Scenario 11 — difficulty is chosen before the game, then shown on the page
    page = client.get("/demo").get_data(as_text=True)
    for needle in ('id="difficulty-options"', "简单", "中等", "困难"):
        assert needle in page
    for difficulty in ("easy", "medium", "hard"):
        created = client.post(
            "/api/game", json={"hero_key": "warrior", "ai_difficulty": difficulty}
        )
        assert created.status_code == 201
        assert created.get_json()["data"]["ai_difficulty"] == difficulty
        assert client.get("/api/game").get_json()["data"]["ai_difficulty"] == difficulty
    assert (
        client.post("/api/game", json={"hero_key": "warrior"}).get_json()["data"][
            "ai_difficulty"
        ]
        == "medium"
    )
    rejected = client.post(
        "/api/game", json={"hero_key": "warrior", "ai_difficulty": "nightmare"}
    )
    assert rejected.status_code == 422
    assert rejected.get_json()["error"]["code"] == "INVALID_DIFFICULTY"
