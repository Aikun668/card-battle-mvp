import random

from app import create_app
from game.battle import LEGACY_ENEMY_HERO_KEY, ROUND_LIMIT, BattleState
from game.catalog import CARDS, HEROES
from game.models import Side
from game.session_state import save_battle


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


def start_player_turn_battle(client, json):
    """创建对局并把状态推进到玩家回合（测试脚手架）。

    电脑先手的开局回合可能停在响应窗口等玩家决定；这里替测试放弃响应，
    返回已经交回玩家回合的状态。专门验证创建契约本身的用例不要用它。
    """
    response = client.post("/api/game", json=json)
    data = response.get_json()["data"]
    guard = 0
    while data and data["phase"] == "RESPONSE" and guard < 6:
        response = client.post("/api/game/actions/respond", json={"action": "pass"})
        data = response.get_json()["data"]
        guard += 1
    return response


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
    # 电脑先手时创建可能停在响应窗口——那也是"等玩家决定"的合法状态。
    assert state["phase"] in ("PLAYER_TURN", "RESPONSE")
    assert state["round_number"] == 1
    # 先手方第 1 个回合只有 2 点能量；后手正常 3 点。
    if state["starting_side"] == "player":
        assert state["player"]["energy"] == 2
    else:
        assert state["player"]["energy"] == 3
    assert len(state["player"]["hand"]) == 5
    assert all("name" in card and "cost" in card for card in state["player"]["hand"])
    assert "enemy_hand" not in state
    assert "draw_pile" not in state
    assert "enemy_draw_pile" not in state


def test_api_card_action_and_end_turn_return_updated_public_state(tmp_path):
    client = make_client(tmp_path)
    start_player_turn_battle(client, json={"hero_key": "warrior"})
    with client.session_transaction() as session:
        player = side_state(session, "player")
        player["hand"] = [{"id": "player-slash", "key": "slash"}]
        # 本用例验证"出牌扣 1 点能量"，先给足 3 点（先手方首回合只有 2 点）。
        player["combatant"]["energy"] = 3
        # 电脑先手时可能已经给自己叠了护盾、装上铁甲，先清掉才好验证伤害。
        enemy = side_state(session, "enemy")
        enemy["combatant"]["shield"] = 0
        enemy["armor"] = None
        drop_enemy_dodge(session)
        session.modified = True
    state = client.get("/api/game").get_json()["data"]
    card_id = next(
        card["id"] for card in state["player"]["hand"] if card["key"] == "slash"
    )
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


def test_api_end_turn_on_the_last_round_returns_a_result_instead_of_an_error(tmp_path):
    client = make_client(tmp_path)
    start_player_turn_battle(client, json={"hero_key": "warrior"})
    with client.session_transaction() as session:
        battle = session["battle"]
        # 让玩家当后手方：他结束回合就正好打满 10 回合，收尾判定由这一步给出，
        # 后面没有电脑回合可跑，接口不该把它当成动作失败。
        battle["starting_side"] = "enemy"
        battle["round_number"] = ROUND_LIMIT
        battle["phase"] = "PLAYER_TURN"
        # 电脑英雄是随机抽的，血线钉死才能确定性地走到“玩家血多获胜”这一支。
        battle["participants"]["player"]["combatant"]["hp"] = 24
        battle["participants"]["enemy"]["combatant"]["hp"] = 20
        session.modified = True

    response = client.post("/api/game/actions/end-turn")

    assert response.status_code == 200
    assert response.get_json()["data"]["phase"] == "VICTORY"


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
    start_player_turn_battle(client, json={"hero_key": "warrior", "ai_difficulty": "easy"})

    assert client.get("/api/game").get_json()["data"]["ai_difficulty"] == "easy"

    after_turn = client.post("/api/game/actions/end-turn").get_json()["data"]
    assert after_turn["ai_difficulty"] == "easy"


def test_public_state_publishes_the_enemy_intent_during_the_player_turn(tmp_path):
    client = make_client(tmp_path)
    start_player_turn_battle(client, json={"hero_key": "warrior"})

    state = client.get("/api/game").get_json()["data"]

    intent = state["enemy"]["intent"]
    assert set(intent) == {"kind", "source", "name", "value", "text"}
    assert intent["kind"] in {"attack", "defend", "heal", "equip", "pass"}
    assert intent["source"] in {"card", "skill", "none"}
    assert intent["value"] >= 0
    assert intent["text"]


def test_enemy_intent_is_deterministic_across_reads(tmp_path):
    client = make_client(tmp_path)
    start_player_turn_battle(client, json={"hero_key": "warrior"})

    first = client.get("/api/game").get_json()["data"]["enemy"]["intent"]
    second = client.get("/api/game").get_json()["data"]["enemy"]["intent"]

    assert first == second


def test_enemy_intent_is_null_outside_the_player_turn(tmp_path):
    client = make_client(tmp_path)
    start_player_turn_battle(client, json={"hero_key": "warrior"})
    with client.session_transaction() as session:
        session["battle"]["phase"] = "VICTORY"
        session.modified = True

    state = client.get("/api/game").get_json()["data"]

    assert state["enemy"]["intent"] is None


def test_enemy_intent_points_at_something_the_enemy_actually_has(tmp_path):
    client = make_client(tmp_path)
    start_player_turn_battle(client, json={"hero_key": "warrior"})
    with client.session_transaction() as session:
        enemy = side_state(session, "enemy")
        hand_names = {CARDS[card["key"]].name for card in enemy["hand"]}
        skill_name = HEROES[enemy["hero_key"]].skill_name

    intent = client.get("/api/game").get_json()["data"]["enemy"]["intent"]

    if intent["source"] == "skill":
        assert intent["name"] == skill_name
    else:
        assert intent["name"] in hand_names


def test_enemy_intent_does_not_leak_the_hidden_hand(tmp_path):
    client = make_client(tmp_path)
    start_player_turn_battle(client, json={"hero_key": "warrior"})
    before = client.get("/api/game").get_json()["data"]["enemy"]["intent"]
    with client.session_transaction() as session:
        side_state(session, "player")["hand"] = [{"id": "hidden", "key": "fireball"}]
        session.modified = True

    state = client.get("/api/game").get_json()["data"]

    assert state["enemy"]["intent"] == before
    assert "hand" not in state["enemy"]
    assert "draw_pile" not in state["enemy"]


def test_catalog_marks_exhaust_cards(tmp_path):
    client = make_client(tmp_path)

    cards = client.get("/api/cards").get_json()["data"]
    execute = next(card for card in cards if card["key"] == "execute")
    slash = next(card for card in cards if card["key"] == "slash")

    assert execute["exhaust"] is True
    assert slash["exhaust"] is False


def test_public_state_publishes_the_exhaust_pile(tmp_path):
    client = make_client(tmp_path)
    start_player_turn_battle(client, json={"hero_key": "warrior"})

    state = client.get("/api/game").get_json()["data"]

    assert state["player"]["exhaust_pile"] == []
    assert state["enemy"]["exhaust_pile"] == []


def test_api_rejects_actions_without_a_live_game(tmp_path):
    client = make_client(tmp_path)

    response = client.post("/api/game/actions/card", json={"card_id": "missing-card"})

    assert response.status_code == 404
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "NO_ACTIVE_GAME"


def test_api_action_error_keeps_state_in_response(tmp_path):
    client = make_client(tmp_path)
    start_player_turn_battle(client, json={"hero_key": "warrior"})
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
    start_player_turn_battle(client, json={"hero_key": "warrior"})

    response = client.post("/api/game/restart")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "data": None, "error": None}
    assert client.get("/api/game").status_code == 404


def test_api_pauses_enemy_attack_and_accepts_dodge_response(tmp_path):
    client = make_client(tmp_path)
    start_player_turn_battle(client, json={"hero_key": "warrior"})
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
        "attacker": "enemy",
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
    start_player_turn_battle(client, json={"hero_key": "warrior"})
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


def test_public_state_shows_both_sides_equipment_symmetrically(tmp_path):
    client = make_client(tmp_path)
    with client.session_transaction() as session:
        save_battle(
            session,
            BattleState.create("warrior", random.Random(7), starting_side=Side.PLAYER),
        )
        session.modified = True

    state = client.get("/api/game").get_json()["data"]

    # 两个槽位任何时刻都在，没装备时是 None，前端可以无条件读。
    assert state["player"]["equipment"] == {"weapon": None, "armor": None}
    assert state["enemy"]["equipment"] == {"weapon": None, "armor": None}
    assert "hand" not in state["enemy"]
    assert "draw_pile" not in state["enemy"]


def test_public_state_shows_equipment_after_a_card_is_played(tmp_path):
    client = make_client(tmp_path)
    with client.session_transaction() as session:
        save_battle(
            session,
            BattleState.create("warrior", random.Random(7), starting_side=Side.PLAYER),
        )
        side_state(session, "player")["hand"] = [
            {"id": "player-longsword", "key": "longsword"}
        ]
        session.modified = True

    response = client.post(
        "/api/game/actions/card", json={"card_id": "player-longsword"}
    )

    assert response.status_code == 200
    state = response.get_json()["data"]
    assert state["player"]["equipment"] == {
        "weapon": {
            "key": "longsword",
            "name": "长剑",
            "cost": 1,
            "effect_type": "equip",
            "value": 2,
            "exhaust": False,
            "text": "装备到武器槽：每回合第一次使用斩击时额外造成 2 点伤害",
        },
        "armor": None,
    }
    # 装备是自己身上看得见的东西，但也不会跑到对面身上去。
    assert state["enemy"]["equipment"] == {"weapon": None, "armor": None}


def test_public_state_shows_both_public_resources_but_not_enemy_hand(tmp_path):
    client = make_client(tmp_path)
    # 先手由 RNG 决定，这里直接把玩家先手的开局写进 session。
    # 先手方第 1 个回合只有 2 点能量，电脑（后手）是 3 点。
    with client.session_transaction() as session:
        save_battle(
            session,
            BattleState.create("mage", random.Random(7), starting_side=Side.PLAYER),
        )
        session.modified = True

    state = client.get("/api/game").get_json()["data"]

    assert state["player"]["energy"] == 2
    assert state["enemy"]["energy"] == 3
    assert state["player"]["hero"]["key"] == "mage"
    assert state["player"]["hero"]["name"] == "法师"
    assert state["enemy"]["hero"]["key"] in {"warrior", "mage", "ranger"}
    assert state["enemy"]["hero"]["max_hp"] == state["enemy"]["max_hp"]
    assert state["enemy"]["skill"]["name"] == state["enemy"]["hero"]["skill_name"]
    assert state["enemy"]["skill"]["cost"] == 2
    assert state["enemy"]["skill"]["used_this_turn"] is False
    assert "hand" not in state["enemy"]
    assert "draw_pile" not in state["enemy"]
    assert "enemy_hand" not in state
    assert "enemy_draw_pile" not in state


def test_a_state_created_with_the_enemy_first_has_already_played_its_opening_turn(
    tmp_path,
):
    client = make_client(tmp_path)
    with client.session_transaction() as session:
        save_battle(
            session,
            BattleState.create("warrior", random.Random(11), starting_side=Side.ENEMY),
        )
        session.modified = True

    state = client.get("/api/game").get_json()["data"]

    assert state["starting_side"] == "enemy"
    assert state["phase"] in {"PLAYER_TURN", "VICTORY", "DEFEAT", "DRAW"}
    assert any(entry.startswith(("电脑使用", "电脑释放技能")) for entry in state["log"])
    # 电脑先手跑完后轮到玩家，玩家资源按自己的回合重置。
    assert state["player"]["energy"] == 3


def test_create_game_never_hands_back_a_mid_enemy_turn(tmp_path):
    client = make_client(tmp_path)
    first_movers = set()

    for _ in range(20):
        response = client.post("/api/game", json={"hero_key": "warrior"})

        assert response.status_code == 201
        state = response.get_json()["data"]
        # 电脑先手的开局回合在创建流程里推到"需要玩家决定的点"为止：
        # 玩家回合、响应窗口（等玩家响应）或终局；绝不把电脑回合留在外面。
        assert state["phase"] in {
            "PLAYER_TURN",
            "RESPONSE",
            "VICTORY",
            "DEFEAT",
            "DRAW",
        }
        if state["phase"] == "RESPONSE":
            assert state["response"]["active"] is True
        first_movers.add(state["starting_side"])

    assert first_movers == {"player", "enemy"}


def test_public_state_keeps_both_sides_resources_across_refreshes(tmp_path):
    client = make_client(tmp_path)
    start_player_turn_battle(client, json={"hero_key": "warrior", "ai_difficulty": "hard"})
    with client.session_transaction() as session:
        player = side_state(session, "player")
        player["combatant"]["energy"] = 2
        player["hand"] = [{"id": "player-dodge", "key": "dodge"}]
        player["skill_used_this_turn"] = True
        session["battle"]["starting_side"] = "player"
        session["battle"]["phase"] = "PLAYER_TURN"
        freeze_enemy_hand(session, ENEMY_DOUBLE_HEAVY)
        pin_enemy_warrior(session)
        session.modified = True

    client.post("/api/game/actions/end-turn")
    first = client.get("/api/game").get_json()["data"]
    second = client.get("/api/game").get_json()["data"]

    assert first == second
    assert first["phase"] == "RESPONSE"
    assert first["response"]["active"] is True
    assert first["response"]["damage"] == 10
    assert first["player"]["hero"]["key"] == "warrior"
    assert first["player"]["skill"]["used_this_turn"] is True
    assert first["player"]["energy"] == 2
    assert first["enemy"]["hero"]["key"] == "warrior"
    assert first["enemy"]["skill"]["name"] == "守护"
    # 电脑打完一张重击后还剩 1 点能量，这份公开资源刷新后照样能看到。
    assert first["enemy"]["energy"] == 1


def test_public_state_serves_a_legacy_flat_session_without_error(tmp_path):
    client = make_client(tmp_path)
    with client.session_transaction() as session:
        session["battle"] = {
            "hero": {"key": "mage"},
            "player": {
                "name": "法师",
                "max_hp": 24,
                "hp": 20,
                "shield": 3,
                "energy": 2,
            },
            "hand": [{"id": "c1", "key": "slash"}],
            "draw_pile": ["slash", "shield"],
            "discard_pile": ["heal"],
            "skill_used_this_turn": True,
            "enemy": {"name": "电脑", "max_hp": 28, "hp": 12, "shield": 0, "energy": 1},
            "enemy_hand": [{"id": "e1", "key": "slash"}],
            "enemy_draw_pile": ["heavy_strike"],
            "enemy_discard_pile": [],
            "round_number": 4,
            "phase": "PLAYER_TURN",
            "log": ["旧存档"],
        }
        session.modified = True

    response = client.get("/api/game")

    assert response.status_code == 200
    state = response.get_json()["data"]
    assert state["round_number"] == 4
    assert state["player"]["hero"]["key"] == "mage"
    assert state["player"]["hp"] == 20
    assert state["enemy"]["hero"]["key"] == LEGACY_ENEMY_HERO_KEY
    assert state["enemy"]["max_hp"] == HEROES[LEGACY_ENEMY_HERO_KEY].max_hp
    assert state["enemy"]["hp"] == 12
    assert [card["key"] for card in state["player"]["hand"]] == ["slash"]
    assert "enemy_hand" not in state
