from app import create_app
from game.battle import ROUND_LIMIT
from game.catalog import HEROES


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


# 电脑英雄是随机的，法师技能（2 费 10 伤）与重击同分，会挤进随机池；
# 固定成战士后它的 8 点护盾技能低于下面两张重击，随机池里只剩伤害牌。
ENEMY_DOUBLE_HEAVY = [
    {"id": "enemy-heavy-1", "key": "heavy_strike"},
    {"id": "enemy-heavy-2", "key": "heavy_strike"},
]


def pin_enemy_warrior(session: dict) -> None:
    """把电脑钉成满血战士，让它的技能评分稳定落在两张重击之下。"""
    enemy = side_state(session, "enemy")
    hero = HEROES["warrior"]
    enemy["hero_key"] = hero.key
    enemy["combatant"]["max_hp"] = hero.max_hp
    enemy["combatant"]["hp"] = hero.max_hp


def test_root_is_backend_health_metadata_and_demo_is_explicit(tmp_path):
    client = make_client(tmp_path)

    root = client.get("/")
    assert root.status_code == 200
    assert root.get_json() == {
        "service": "card-battle",
        "status": "ok",
        "api_base": "/api",
        "demo": "/demo",
    }
    assert client.get("/demo").status_code == 200
    assert client.get("/heroes").status_code == 404
    assert client.get("/battle").status_code == 404


def test_catalog_endpoints_return_data_for_a_future_frontend(tmp_path):
    client = make_client(tmp_path)

    heroes = client.get("/api/heroes")
    assert heroes.status_code == 200
    hero_data = heroes.get_json()
    assert hero_data["ok"] is True
    assert {hero["key"] for hero in hero_data["data"]} == {
        "warrior",
        "mage",
        "ranger",
    }

    cards = client.get("/api/cards")
    assert cards.status_code == 200
    card_data = cards.get_json()
    assert card_data["ok"] is True
    assert any(card["key"] == "slash" for card in card_data["data"])


def test_create_game_returns_public_state_without_hidden_deck_data(tmp_path):
    client = make_client(tmp_path)

    response = client.post("/api/game", json={"hero_key": "warrior"})

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["ok"] is True
    state = payload["data"]
    assert state["phase"] == "PLAYER_TURN"
    assert state["round_number"] == 1
    assert state["player"]["energy"] == 3
    assert len(state["hand"]) == 5
    assert all("name" in card and "cost" in card for card in state["hand"])
    assert "enemy_hand" not in state
    assert "draw_pile" not in state
    assert "enemy_draw_pile" not in state


def test_api_card_action_and_end_turn_return_updated_public_state(tmp_path):
    client = make_client(tmp_path)
    client.post("/api/game", json={"hero_key": "warrior"})
    with client.session_transaction() as session:
        side_state(session, "player")["hand"] = [{"id": "player-slash", "key": "slash"}]
        # 电脑先手时可能已经给自己叠了护盾，护盾现在会跨回合保留，先清零才好验证伤害。
        side_state(session, "enemy")["combatant"]["shield"] = 0
        drop_enemy_dodge(session)
        session.modified = True
    state = client.get("/api/game").get_json()["data"]
    card_id = next(card["id"] for card in state["hand"] if card["key"] == "slash")
    enemy_hp_before = state["enemy"]["hp"]

    card_response = client.post("/api/game/actions/card", json={"card_id": card_id})
    assert card_response.status_code == 200
    after_card = card_response.get_json()["data"]
    assert after_card["enemy"]["hp"] == enemy_hp_before - 6
    assert after_card["player"]["energy"] == 2

    with client.session_transaction() as session:
        player = side_state(session, "player")
        player["hand"] = [card for card in player["hand"] if card["key"] != "dodge"]
        freeze_enemy_hand(session, [{"id": "enemy-shield", "key": "shield"}])
        session.modified = True

    end_turn_response = client.post("/api/game/actions/end-turn")
    assert end_turn_response.status_code == 200
    after_turn = end_turn_response.get_json()["data"]
    assert after_turn["phase"] == "PLAYER_TURN"
    assert after_turn["round_number"] == 2
    assert after_turn["player"]["energy"] == 3


def test_api_end_turn_on_the_last_round_returns_a_draw_instead_of_an_error(tmp_path):
    client = make_client(tmp_path)
    client.post("/api/game", json={"hero_key": "warrior"})
    with client.session_transaction() as session:
        battle = session["battle"]
        # 让玩家当后手方：他结束回合就正好打满 10 回合，平局由这一步判定，
        # 后面没有电脑回合可跑，接口不该把它当成动作失败。
        battle["starting_side"] = "enemy"
        battle["round_number"] = ROUND_LIMIT
        battle["phase"] = "PLAYER_TURN"
        session.modified = True

    response = client.post("/api/game/actions/end-turn")

    assert response.status_code == 200
    assert response.get_json()["data"]["phase"] == "DRAW"


def test_create_game_defaults_to_medium_ai_difficulty(tmp_path):
    client = make_client(tmp_path)

    response = client.post("/api/game", json={"hero_key": "mage"})

    assert response.status_code == 201
    assert response.get_json()["data"]["ai_difficulty"] == "medium"


def test_create_game_accepts_an_explicit_ai_difficulty(tmp_path):
    client = make_client(tmp_path)

    response = client.post(
        "/api/game", json={"hero_key": "mage", "ai_difficulty": "hard"}
    )

    assert response.status_code == 201
    assert response.get_json()["data"]["ai_difficulty"] == "hard"


def test_create_game_rejects_an_unknown_ai_difficulty(tmp_path):
    client = make_client(tmp_path)

    response = client.post(
        "/api/game", json={"hero_key": "mage", "ai_difficulty": "nightmare"}
    )

    assert response.status_code == 422
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "INVALID_DIFFICULTY"


def test_ai_difficulty_survives_reads_and_enemy_turns(tmp_path):
    client = make_client(tmp_path)
    client.post("/api/game", json={"hero_key": "warrior", "ai_difficulty": "easy"})

    assert client.get("/api/game").get_json()["data"]["ai_difficulty"] == "easy"

    after_turn = client.post("/api/game/actions/end-turn").get_json()["data"]
    assert after_turn["ai_difficulty"] == "easy"


def test_api_rejects_actions_without_a_live_game(tmp_path):
    client = make_client(tmp_path)

    response = client.post("/api/game/actions/card", json={"card_id": "missing-card"})

    assert response.status_code == 404
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "NO_ACTIVE_GAME"


def test_api_action_error_keeps_state_in_response(tmp_path):
    client = make_client(tmp_path)
    client.post("/api/game", json={"hero_key": "warrior"})
    before = client.get("/api/game").get_json()["data"]

    response = client.post("/api/game/actions/card", json={"card_id": "not-in-hand"})

    assert response.status_code == 422
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "ACTION_REJECTED"
    assert payload["data"]["player"] == before["player"]
    assert payload["data"]["enemy"] == before["enemy"]


def test_api_restart_clears_the_current_game(tmp_path):
    client = make_client(tmp_path)
    client.post("/api/game", json={"hero_key": "warrior"})

    response = client.post("/api/game/restart")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "data": None, "error": None}
    assert client.get("/api/game").status_code == 404


def test_api_pauses_enemy_attack_and_accepts_dodge_response(tmp_path):
    client = make_client(tmp_path)
    client.post("/api/game", json={"hero_key": "warrior"})
    with client.session_transaction() as session:
        player = side_state(session, "player")
        player["combatant"]["energy"] = 2
        player["hand"] = [{"id": "player-dodge", "key": "dodge"}]
        freeze_enemy_hand(session, ENEMY_DOUBLE_HEAVY)
        pin_enemy_warrior(session)
        hp_before = player["combatant"]["hp"]
        session.modified = True

    end_turn = client.post("/api/game/actions/end-turn")
    paused = end_turn.get_json()["data"]

    assert end_turn.status_code == 200
    assert paused["phase"] == "RESPONSE"
    assert paused["player"]["hp"] == hp_before
    assert paused["player"]["energy"] == 2
    assert paused["response"] == {
        "active": True,
        "card_name": "重击",
        "damage": 10,
        "dodge_cost": 1,
    }
    assert paused["available_actions"]["respond"] == {
        "dodge": True,
        "pass": True,
    }

    response = client.post(
        "/api/game/actions/respond",
        json={"action": "dodge"},
    )
    state = response.get_json()["data"]

    assert response.status_code == 200
    assert state["phase"] == "PLAYER_TURN"
    assert state["player"]["hp"] == hp_before
    assert state["player"]["energy"] == 3
    assert "玩家使用【闪避】，抵消了本次伤害" in state["log"]


def test_api_can_pass_enemy_attack_response(tmp_path):
    client = make_client(tmp_path)
    client.post("/api/game", json={"hero_key": "warrior"})
    with client.session_transaction() as session:
        player = side_state(session, "player")
        player["combatant"]["energy"] = 1
        player["combatant"]["shield"] = 4
        player["hand"] = [{"id": "player-dodge", "key": "dodge"}]
        freeze_enemy_hand(session, ENEMY_DOUBLE_HEAVY)
        pin_enemy_warrior(session)
        hp_before = player["combatant"]["hp"]
        session.modified = True

    client.post("/api/game/actions/end-turn")
    response = client.post(
        "/api/game/actions/respond",
        json={"action": "pass"},
    )
    state = response.get_json()["data"]

    assert response.status_code == 200
    assert state["phase"] == "PLAYER_TURN"
    # 4 点护盾先吸收，剩下 6 点才扣生命。
    assert state["player"]["hp"] == hp_before - 6
    assert state["player"]["shield"] == 0
    assert "电脑使用【重击】，对你造成 10 点伤害" in state["log"]
