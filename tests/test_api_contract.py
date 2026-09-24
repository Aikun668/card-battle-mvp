"""API 契约测试：把 /api 的公开形状锁死（契约 v1，2026-09-23 冻结）。

这些用例只断言"形状、枚举与状态码"，不断言战斗行为（行为用例在 test_api.py 等）。
契约冻结后允许的改动只有加法：新增键、新增可选参数、枚举新成员。
任何删键 / 改形状 / 改语义的改动都应该先在这里变红，再走评审决定是否升 v2。
"""

import random

from app import create_app
from game.battle import ROUND_LIMIT, BattleState
from game.catalog import CARDS, HEROES
from game.models import Side
from game.session_state import save_battle

# ---- 契约常量：与 docs/api-contract.md 的总表一一对应 ----

PHASES = {"PLAYER_TURN", "RESPONSE", "VICTORY", "DEFEAT", "DRAW"}
# 双人模式把 ENEMY_TURN 提升为一等公民（含义是"等座位 2 操作"）。
PVP_PHASES = PHASES | {"ENEMY_TURN"}
SIDES = {"player", "enemy"}
DIFFICULTIES = {"easy", "medium", "hard"}
EFFECT_TYPES = {"damage", "shield", "heal", "dodge", "equip", "charge"}
INTENT_KINDS = {"attack", "defend", "heal", "equip", "charge", "pass"}
INTENT_SOURCES = {"card", "skill", "none"}
RESULT_REASONS = {"kill", "hp", "shield", "draw"}
SKILL_TYPES = {"shield", "damage", "damage_draw"}

STATE_KEYS = {
    "phase",
    "mode",
    "viewer",
    "round_number",
    "starting_side",
    "ai_difficulty",
    "player",
    "enemy",
    "response",
    "available_actions",
    "result",
    "log",
}
SIDE_KEYS = {
    "name",
    "max_hp",
    "hp",
    "shield",
    "energy",
    "hero",
    "skill",
    "equipment",
    "bonus_energy_next_turn",
    "exhaust_pile",
    "negate_available",
}
CARD_KEYS = {"key", "name", "cost", "effect_type", "value", "exhaust", "text"}
HERO_KEYS = {"key", "name", "max_hp", "skill_name", "skill_type", "skill_value"}
HERO_ENTRY_KEYS = HERO_KEYS | {"description", "deck"}
HAND_CARD_KEYS = CARD_KEYS | {"id"}
SKILL_KEYS = {"name", "type", "value", "cost", "used_this_turn"}
EQUIPMENT_KEYS = {"weapon", "armor"}
INTENT_KEYS = {"kind", "source", "name", "value", "text"}
RESPONSE_KEYS = {"active", "kind", "attacker", "card_name", "damage", "dodge_cost"}
ACTIONS_KEYS = {"play_card", "use_skill", "end_turn", "respond"}
RESPOND_KEYS = {"dodge", "negate", "pass"}
RESULT_KEYS = {"winner", "reason", "text"}
ERROR_KEYS = {"code", "message"}
ENVELOPE_KEYS = {"ok", "data", "error"}


def make_client(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DATABASE": str(tmp_path / "contract.sqlite3"),
        }
    )
    return app.test_client()


def install_battle(client, *, starting_side=Side.PLAYER, seed=7):
    """把一局确定性的对局写进 session，避开 RNG 抽先手带来的形状差异。"""
    with client.session_transaction() as session:
        save_battle(
            session,
            BattleState.create("warrior", random.Random(seed), starting_side=starting_side),
        )
        session.modified = True


def get_state(client):
    return client.get("/api/game").get_json()["data"]


def test_heroes_catalog_contract(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/api/heroes")

    assert response.status_code == 200
    payload = response.get_json()
    assert set(payload) == ENVELOPE_KEYS
    assert payload["ok"] is True and payload["error"] is None

    entries = payload["data"]
    assert {entry["key"] for entry in entries} == set(HEROES)
    for entry in entries:
        assert set(entry) == HERO_ENTRY_KEYS
        assert entry["name"] and entry["skill_name"]
        assert entry["skill_type"] in SKILL_TYPES
        assert isinstance(entry["max_hp"], int) and entry["max_hp"] > 0
        assert isinstance(entry["skill_value"], int) and entry["skill_value"] >= 0
        assert entry["description"], "选人页的描述文案不允许为空"
        # 卡组汇总：每项形状固定，条目总数必须等于真实牌组的张数。
        for item in entry["deck"]:
            assert set(item) == {"key", "name", "count"}
            assert item["key"] in CARDS
            assert item["name"] == CARDS[item["key"]].name
            assert isinstance(item["count"], int) and item["count"] >= 1
        total = sum(item["count"] for item in entry["deck"])
        assert total == 16, f"{entry['key']} 的卡组汇总张数与牌组不一致"


def test_cards_catalog_contract(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/api/cards")

    assert response.status_code == 200
    payload = response.get_json()
    assert set(payload) == ENVELOPE_KEYS
    assert payload["ok"] is True and payload["error"] is None

    cards = payload["data"]
    assert {card["key"] for card in cards} == set(CARDS)
    for card in cards:
        assert set(card) == CARD_KEYS
        assert card["effect_type"] in EFFECT_TYPES
        assert isinstance(card["cost"], int) and card["cost"] >= 0
        assert isinstance(card["value"], int) and card["value"] >= 0
        assert isinstance(card["exhaust"], bool)
        assert card["text"], "每张牌都必须有可展示的效果文案"


def test_public_state_contract(tmp_path):
    client = make_client(tmp_path)
    install_battle(client)

    state = get_state(client)

    assert set(state) == STATE_KEYS
    assert state["mode"] == "pve"
    assert state["viewer"] == "player"
    assert state["phase"] in PHASES
    assert state["starting_side"] in SIDES
    assert state["ai_difficulty"] in DIFFICULTIES
    assert isinstance(state["round_number"], int) and state["round_number"] >= 1
    assert isinstance(state["log"], list)
    assert all(isinstance(entry, str) for entry in state["log"])

    # 双方公开字段完全对称，只差各自私有的那一个键。
    assert set(state["player"]) == SIDE_KEYS | {"hand"}
    assert set(state["enemy"]) == SIDE_KEYS | {"intent"}

    for side in ("player", "enemy"):
        block = state[side]
        assert set(block["hero"]) == HERO_KEYS
        assert block["hero"]["key"] in HEROES
        assert set(block["skill"]) == SKILL_KEYS
        assert block["skill"]["type"] in SKILL_TYPES
        assert set(block["equipment"]) == EQUIPMENT_KEYS
        assert isinstance(block["exhaust_pile"], list)
        assert all(key in CARDS for key in block["exhaust_pile"])

    for card in state["player"]["hand"]:
        assert set(card) == HAND_CARD_KEYS

    assert set(state["response"]) == RESPONSE_KEYS
    assert set(state["available_actions"]) == ACTIONS_KEYS
    assert set(state["available_actions"]["respond"]) == RESPOND_KEYS
    assert state["result"] is None, "非终局时 result 恒为 null"

    # 隐私边界：电脑的手牌与抽牌堆不允许以任何键名出现在响应里。
    forbidden = {"enemy_hand", "enemy_draw_pile", "enemy_discard_pile"}
    assert not (set(state) & forbidden)
    assert not (set(state["enemy"]) & {"hand", "draw_pile", "discard_pile"})


def test_pvp_state_contract_keeps_enemy_turn_in_the_enum(tmp_path):
    """双人模式下 ENEMY_TURN 是一等公民：第二座位先手时创建即返回它。

    契约枚举必须把这条形状钉住，而不是只靠行为测试在兜。
    """
    client = make_client(tmp_path)
    with client.session_transaction() as session:
        save_battle(
            session,
            BattleState.create(
                "warrior",
                random.Random(7),
                starting_side=Side.ENEMY,
                mode="pvp",
                opponent_hero_key="mage",
            ),
        )
        session.modified = True

    state = get_state(client)

    assert set(state) == STATE_KEYS
    assert state["mode"] == "pvp"
    assert state["viewer"] == "player"
    assert state["phase"] in PVP_PHASES
    assert state["phase"] == "ENEMY_TURN"
    # 视角语义在双人契约里同样成立：手牌只在自己一侧，intent 恒为空。
    assert "hand" in state["player"] and "hand" not in state["enemy"]
    assert state["enemy"]["intent"] is None


def test_intent_contract(tmp_path):
    client = make_client(tmp_path)
    install_battle(client)

    intent = get_state(client)["enemy"]["intent"]

    assert set(intent) == INTENT_KEYS
    assert intent["kind"] in INTENT_KINDS
    assert intent["source"] in INTENT_SOURCES
    assert isinstance(intent["value"], int) and intent["value"] >= 0
    assert intent["text"]


def test_result_contract_for_kill_settlement_and_draw(tmp_path):
    client = make_client(tmp_path)
    install_battle(client, starting_side=Side.ENEMY)

    # 击杀：电脑血量归零、阶段推进到终局后读取。
    with client.session_transaction() as session:
        battle = session["battle"]
        battle["participants"]["enemy"]["combatant"]["hp"] = 0
        battle["phase"] = "VICTORY"
        session.modified = True
    kill = get_state(client)["result"]
    assert set(kill) == RESULT_KEYS
    assert kill["winner"] == "player" and kill["reason"] == "kill"
    assert kill["text"]

    # 结算：玩家是后手方，第 10 回合结束回合时收尾判定，血多者胜。
    with client.session_transaction() as session:
        battle = session["battle"]
        battle["phase"] = "PLAYER_TURN"
        battle["round_number"] = ROUND_LIMIT
        battle["participants"]["player"]["combatant"]["hp"] = 24
        battle["participants"]["enemy"]["combatant"]["hp"] = 20
        session.modified = True
    after = client.post("/api/game/actions/end-turn").get_json()["data"]
    assert set(after["result"]) == RESULT_KEYS
    assert after["result"]["winner"] == "player"
    assert after["result"]["reason"] == "hp"

    # 护盾更厚：血量相同、护盾不同时的结算分支。
    with client.session_transaction() as session:
        battle = session["battle"]
        battle["phase"] = "PLAYER_TURN"
        battle["round_number"] = ROUND_LIMIT
        for side in ("player", "enemy"):
            battle["participants"][side]["combatant"]["hp"] = 20
        battle["participants"]["player"]["combatant"]["shield"] = 5
        battle["participants"]["enemy"]["combatant"]["shield"] = 0
        session.modified = True
    after = client.post("/api/game/actions/end-turn").get_json()["data"]
    assert after["phase"] == "VICTORY"
    assert after["result"]["winner"] == "player"
    assert after["result"]["reason"] == "shield"

    # 完全平局：血量与护盾都相同。
    with client.session_transaction() as session:
        battle = session["battle"]
        battle["phase"] = "PLAYER_TURN"
        battle["round_number"] = ROUND_LIMIT
        for side in ("player", "enemy"):
            battle["participants"][side]["combatant"]["hp"] = 20
            battle["participants"][side]["combatant"]["shield"] = 3
        session.modified = True
    after = client.post("/api/game/actions/end-turn").get_json()["data"]
    assert after["phase"] == "DRAW"
    assert set(after["result"]) == RESULT_KEYS
    assert after["result"]["winner"] is None
    assert after["result"]["reason"] == "draw"


def test_error_envelope_and_status_codes_contract(tmp_path):
    client = make_client(tmp_path)

    # 没有对局：404。
    missing = client.post("/api/game/actions/card", json={"card_id": "x"})
    assert missing.status_code == 404
    payload = missing.get_json()
    assert set(payload) == ENVELOPE_KEYS
    assert payload["ok"] is False and payload["data"] is None
    assert set(payload["error"]) == ERROR_KEYS
    assert payload["error"]["code"] == "NO_ACTIVE_GAME"

    # 非法英雄与难度：422。
    invalid_hero = client.post("/api/game", json={"hero_key": "rogue"})
    assert invalid_hero.status_code == 422
    assert invalid_hero.get_json()["error"]["code"] == "INVALID_HERO"

    invalid_difficulty = client.post(
        "/api/game", json={"hero_key": "warrior", "ai_difficulty": "nightmare"}
    )
    assert invalid_difficulty.status_code == 422
    assert invalid_difficulty.get_json()["error"]["code"] == "INVALID_DIFFICULTY"

    invalid_mode = client.post(
        "/api/game", json={"hero_key": "warrior", "mode": "coop"}
    )
    assert invalid_mode.status_code == 422
    assert invalid_mode.get_json()["error"]["code"] == "INVALID_MODE"

    # 对手英雄在两种模式下都校验：曾经 pve 传非法值会在模型层 KeyError 变成 500。
    invalid_opponent = client.post(
        "/api/game", json={"hero_key": "warrior", "opponent_hero_key": "dragon"}
    )
    assert invalid_opponent.status_code == 422
    assert invalid_opponent.get_json()["error"]["code"] == "INVALID_HERO"

    # 缺字段：400。
    install_battle(client)
    bad_request = client.post("/api/game/actions/card", json={})
    assert bad_request.status_code == 400
    assert bad_request.get_json()["error"]["code"] == "INVALID_REQUEST"

    bad_response_action = client.post(
        "/api/game/actions/respond", json={"action": "run"}
    )
    assert bad_response_action.status_code == 400
    assert bad_response_action.get_json()["error"]["code"] == "INVALID_REQUEST"

    # 座位校验：值非法、或该座位由电脑操作（人机模式的 enemy）都是 400 INVALID_SEAT。
    bad_seat = client.post("/api/game/actions/end-turn", json={"seat": "seat3"})
    assert bad_seat.status_code == 400
    assert bad_seat.get_json()["error"]["code"] == "INVALID_SEAT"

    ai_seat = client.post("/api/game/actions/end-turn", json={"seat": "enemy"})
    assert ai_seat.status_code == 400
    assert ai_seat.get_json()["error"]["code"] == "INVALID_SEAT"

    # GET 的 seat 走同样的校验（query 参数版本）。
    assert client.get("/api/game?seat=player").status_code == 200
    bad_get_seat = client.get("/api/game?seat=seat9")
    assert bad_get_seat.status_code == 400
    assert bad_get_seat.get_json()["error"]["code"] == "INVALID_SEAT"
    ai_get_seat = client.get("/api/game?seat=enemy")
    assert ai_get_seat.status_code == 400
    assert ai_get_seat.get_json()["error"]["code"] == "INVALID_SEAT"

    # 规则拒绝：422，且 data 里带最新公开状态（前端出错即可同步状态）。
    rejected = client.post("/api/game/actions/card", json={"card_id": "not-in-hand"})
    assert rejected.status_code == 422
    payload = rejected.get_json()
    assert payload["error"]["code"] == "ACTION_REJECTED"
    assert set(payload["data"]) == STATE_KEYS


def test_create_game_response_contract(tmp_path):
    client = make_client(tmp_path)

    response = client.post("/api/game", json={"hero_key": "warrior"})

    # 创建成功返回 201；电脑先手的开局回合在创建流程内跑完，绝不把 ENEMY_TURN 留给前端。
    assert response.status_code == 201
    payload = response.get_json()
    assert set(payload) == ENVELOPE_KEYS
    assert payload["ok"] is True and payload["error"] is None
    assert set(payload["data"]) == STATE_KEYS
    assert payload["data"]["mode"] == "pve"
    assert payload["data"]["viewer"] == "player"
    assert payload["data"]["phase"] in {"PLAYER_TURN", "RESPONSE", "VICTORY", "DEFEAT", "DRAW"}


def test_restart_contract(tmp_path):
    client = make_client(tmp_path)
    install_battle(client)

    response = client.post("/api/game/restart")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "data": None, "error": None}
