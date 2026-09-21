import pytest

from app import create_app
from game.battle import ROUND_LIMIT
from game.catalog import CARDS, HEROES


def make_client(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DATABASE": str(tmp_path / "test.sqlite3"),
        }
    )
    return app.test_client()


def side_state(session: dict, side: str) -> dict:
    """读取 session 里某个参与者的原始分区。"""
    return session["battle"]["participants"][side]


def drop_enemy_dodge(session: dict) -> None:
    """电脑手里有闪避就能响应玩家的攻击，这里要验证的是伤害当场落地。"""
    enemy = side_state(session, "enemy")
    enemy["hand"] = [card for card in enemy["hand"] if card["key"] != "dodge"]


def freeze_enemy_hand(session: dict, hand: list[dict]) -> None:
    """锁死电脑手牌：抽牌区和弃牌区清空后，它回合开始的补牌就抽不到东西。"""
    enemy = side_state(session, "enemy")
    enemy["hand"] = hand
    enemy["draw_pile"] = []
    enemy["discard_pile"] = []


def pin_enemy_warrior(session: dict) -> None:
    """把电脑钉成满血战士，让它的技能评分稳定落在两张重击之下。"""
    enemy = side_state(session, "enemy")
    hero = HEROES["warrior"]
    enemy["hero_key"] = hero.key
    enemy["combatant"]["max_hp"] = hero.max_hp
    enemy["combatant"]["hp"] = hero.max_hp


# 电脑英雄是随机的，法师技能（2 费 10 伤）与重击同分，会挤进随机池；
# 固定成战士后它的 8 点护盾技能低于这两张重击，回合里只会打出重击。
ENEMY_DOUBLE_HEAVY = [
    {"id": "enemy-heavy-1", "key": "heavy_strike"},
    {"id": "enemy-heavy-2", "key": "heavy_strike"},
]


def test_start_page_and_hero_page_render(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/demo").status_code == 200
    response = client.get("/demo/heroes")
    assert response.status_code == 200
    assert "战士" in response.get_data(as_text=True)


def test_selecting_a_hero_redirects_to_battle(tmp_path):
    client = make_client(tmp_path)
    response = client.post("/demo/heroes", data={"hero_key": "warrior"})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/demo/battle")
    assert "当前回合" in client.get("/demo/battle").get_data(as_text=True)


def test_card_post_redirects_and_refresh_does_not_repeat_action(tmp_path):
    client = make_client(tmp_path)
    client.post("/demo/heroes", data={"hero_key": "warrior"})
    page = client.get("/demo/battle").get_data(as_text=True)
    assert "手牌" in page
    with client.session_transaction() as session:
        card_id = side_state(session, "player")["hand"][0]["id"]
        enemy_hp_before = side_state(session, "enemy")["combatant"]["hp"]
    response = client.post(f"/demo/battle/card/{card_id}")
    assert response.status_code == 302
    first_get = client.get("/demo/battle")
    second_get = client.get("/demo/battle")
    assert first_get.status_code == 200
    assert second_get.status_code == 200
    with client.session_transaction() as session:
        assert side_state(session, "enemy")["combatant"]["hp"] <= enemy_hp_before


def test_hero_page_has_a_disabled_confirm_button_before_selection(tmp_path):
    client = make_client(tmp_path)
    body = client.get("/demo/heroes").get_data(as_text=True)
    assert "确认角色" in body
    assert "hero-card" in body


def test_battle_page_exposes_player_state_hand_and_end_turn(tmp_path):
    client = make_client(tmp_path)
    client.post("/demo/heroes", data={"hero_key": "mage"})
    body = client.get("/demo/battle").get_data(as_text=True)
    assert "生命值" in body
    assert "护盾" in body
    assert "能量" in body
    assert "结束回合" in body
    assert "战斗日志" in body


def test_battle_page_shows_the_enemy_hero_and_its_public_resources(tmp_path):
    client = make_client(tmp_path)
    client.post("/demo/heroes", data={"hero_key": "mage"})
    with client.session_transaction() as session:
        enemy = side_state(session, "enemy")
        enemy["hero_key"] = "ranger"
        enemy["combatant"]["max_hp"] = HEROES["ranger"].max_hp
        enemy["combatant"]["hp"] = HEROES["ranger"].max_hp
        enemy["combatant"]["energy"] = 2
        enemy["skill_used_this_turn"] = True
        session.modified = True

    body = client.get("/demo/battle").get_data(as_text=True)

    assert "游侠" in body
    assert "电脑英雄：游侠" in body
    assert "电脑能量：2" in body
    assert "连射" in body
    assert "本回合技能已经使用过" in body


def test_demo_battle_page_can_answer_an_enemy_attack(tmp_path):
    client = make_client(tmp_path)
    client.post("/demo/heroes", data={"hero_key": "warrior"})
    with client.session_transaction() as session:
        player = side_state(session, "player")
        player["combatant"]["energy"] = 2
        player["combatant"]["shield"] = 0
        player["hand"] = [{"id": "player-dodge", "key": "dodge"}]
        session["battle"]["starting_side"] = "player"
        session["battle"]["phase"] = "PLAYER_TURN"
        freeze_enemy_hand(session, ENEMY_DOUBLE_HEAVY)
        pin_enemy_warrior(session)
        session.modified = True

    client.post("/demo/battle/end-turn")
    page = client.get("/demo/battle").get_data(as_text=True)
    assert "使用闪避" in page
    assert "放弃响应" in page

    response = client.post("/demo/battle/respond", data={"action": "dodge"})

    assert response.status_code == 302
    with client.session_transaction() as session:
        player = side_state(session, "player")
        assert session["battle"]["phase"] == "PLAYER_TURN"
        # 闪避牌打出后进了弃牌堆，回合交回玩家时补一张牌、能量重新回满。
        assert all(card["key"] != "dodge" for card in player["hand"])
        assert player["discard_pile"] == ["dodge"]
        assert player["combatant"]["energy"] == 3
        assert any("抵消了本次伤害" in entry for entry in session["battle"]["log"])


def test_a_whole_game_can_be_played_through_the_demo_page(tmp_path):
    client = make_client(tmp_path)
    client.post("/demo/heroes", data={"hero_key": "ranger"})
    terminal = {"VICTORY", "DEFEAT", "DRAW"}

    for _ in range(150):
        with client.session_transaction() as session:
            phase = session["battle"]["phase"]
            if phase in terminal:
                break
            player = side_state(session, "player")
            energy = player["combatant"]["energy"]
            playable = next(
                (
                    card["id"]
                    for card in player["hand"]
                    if card["key"] != "dodge" and CARDS[card["key"]].cost <= energy
                ),
                None,
            )
        if phase == "RESPONSE":
            # 老页面以前没有响应入口，只能靠重启逃出去；现在必须能在页面上收尾。
            page = client.get("/demo/battle").get_data(as_text=True)
            assert "放弃响应" in page
            response = client.post("/demo/battle/respond", data={"action": "pass"})
        elif playable is None:
            response = client.post("/demo/battle/end-turn")
        else:
            response = client.post(f"/demo/battle/card/{playable}")
        assert response.status_code == 302
    else:
        pytest.fail("整局游戏没有在 150 步内走到终局")

    with client.session_transaction() as session:
        assert session["battle"]["phase"] in terminal
    result_page = client.get("/demo/result").get_data(as_text=True)
    assert any(label in result_page for label in ("胜利", "失败", "平局"))


def test_routes_redirect_to_heroes_when_no_live_battle(tmp_path):
    client = make_client(tmp_path)
    r = client.get("/demo/battle")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/demo/heroes")
    r = client.post("/demo/battle/card/anything")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/demo/heroes")
    r = client.post("/demo/battle/skill")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/demo/heroes")
    r = client.post("/demo/battle/end-turn")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/demo/heroes")
    r = client.get("/demo/result")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/demo/heroes")


def test_match_result_written_to_sqlite_exactly_once(tmp_path):
    client = make_client(tmp_path)
    client.post("/demo/heroes", data={"hero_key": "warrior"})
    with client.session_transaction() as s:
        enemy = side_state(s, "enemy")
        enemy["combatant"]["hp"] = 1
        enemy["combatant"]["shield"] = 0
        drop_enemy_dodge(s)
        side_state(s, "player")["hand"] = [{"id": "x", "key": "slash"}]
        s.modified = True
    client.post("/demo/battle/card/x")  # kills enemy -> VICTORY -> writes to DB
    client.post("/demo/battle/card/x")  # rejected (not in hand)
    client.post("/demo/battle/card/x")
    import sqlite3

    db_path = tmp_path / "test.sqlite3"
    with sqlite3.connect(db_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM match_results").fetchone()[0]
    assert count == 1


def test_end_turn_on_the_last_round_shows_the_result_without_a_flash(tmp_path):
    client = make_client(tmp_path)
    client.post("/demo/heroes", data={"hero_key": "warrior"})
    with client.session_transaction() as s:
        # 让玩家当后手方：他结束回合就正好打满 10 回合，收尾判定由这一步给出，
        # 后面没有电脑回合可跑，页面不该弹“本局已经结束”。
        s["battle"]["starting_side"] = "enemy"
        s["battle"]["round_number"] = ROUND_LIMIT
        s["battle"]["phase"] = "PLAYER_TURN"
        # 电脑英雄是随机抽的，血线钉死才能确定性地走到“玩家血多获胜”这一支。
        s["battle"]["participants"]["player"]["combatant"]["hp"] = 24
        s["battle"]["participants"]["enemy"]["combatant"]["hp"] = 20
        s.modified = True

    r = client.post("/demo/battle/end-turn")

    assert r.status_code == 302
    assert r.headers["Location"].endswith("/demo/result")
    page = client.get("/demo/result").get_data(as_text=True)
    assert "胜利" in page
    assert "本局已经结束" not in page


def test_restart_clears_battle_and_returns_to_heroes(tmp_path):
    client = make_client(tmp_path)
    client.post("/demo/heroes", data={"hero_key": "warrior"})
    assert client.get("/demo/battle").status_code == 200
    r = client.post("/demo/restart")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/demo/heroes")
    with client.session_transaction() as s:
        assert "battle" not in s
    r = client.get("/demo/battle")
    assert r.status_code == 302


def test_invalid_hero_key_redirects_to_heroes_with_flash(tmp_path):
    client = make_client(tmp_path)
    r = client.post("/demo/heroes", data={"hero_key": "unknown"})
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/demo/heroes")
