"""在线 PvP HTTP 契约测试：逐字段镜像已冻结的《在线PvP接口契约-v1》。

本文件不信任实现细节，只按文档断言线上真实可观测的形状：
统一信封、RoomSnapshot 顶层与子块键集、枚举取值、错误码 → HTTP → data 的映射、
严格请求体校验、revision 乐观并发、缓存禁用、盲选无泄露。

与 test_online_api.py 的分工：那边验证"行为对不对"，这边验证"形状稳不稳"。
"""

import json
import random
from datetime import datetime, timedelta, timezone

from api_routes import ROOM_ERROR_STATUS
from app import create_app
from game.catalog import HEROES

START = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
TTL = timedelta(hours=2)

# --------------------------------------------------------------------------
# 契约常量：与 game.public_state / game.models / 契约 §3 §4 一一对应
# --------------------------------------------------------------------------

ENVELOPE_KEYS = {"ok", "data", "error"}
ERROR_KEYS = {"code", "message"}

ROOM_KEYS = {
    "room_id",
    "room_code",
    "status",
    "revision",
    "match_number",
    "created_at",
    "updated_at",
    "expires_at",
    "invite_url",
}
ROOM_STATUSES = {"WAITING", "HERO_SELECT", "PLAYING", "FINISHED", "EXPIRED"}
YOU_KEYS = {"nickname", "hero_key", "hero_locked", "rematch_confirmed"}
OPPONENT_KEYS = {"nickname", "joined", "hero_locked", "rematch_confirmed"}
REMATCH_KEYS = {"status", "requested_by"}
REMATCH_STATUSES = {"NOT_AVAILABLE", "WAITING_CONFIRMATION"}

BATTLE_KEYS = {
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
PVP_PHASES = {
    "PLAYER_TURN",
    "ENEMY_TURN",
    "RESPONSE",
    "VICTORY",
    "DEFEAT",
    "DRAW",
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
HERO_KEYS = {"key", "name", "max_hp", "skill_name", "skill_type", "skill_value"}
SKILL_KEYS = {"name", "type", "value", "cost", "used_this_turn"}
EQUIPMENT_KEYS = {"weapon", "armor"}
CARD_KEYS = {"key", "name", "cost", "effect_type", "value", "exhaust", "text"}
HAND_CARD_KEYS = CARD_KEYS | {"id"}
RESPONSE_KEYS = {
    "active",
    "kind",
    "attacker",
    "card_name",
    "damage",
    "dodge_cost",
}
ACTIONS_KEYS = {"play_card", "use_skill", "end_turn", "respond"}
RESPOND_KEYS = {"dodge", "negate", "pass"}
RESULT_KEYS = {"winner", "reason", "text"}

# 契约 §6.1：只有这 5 个错误码在 data 里携带最新 RoomSnapshot。
SNAPSHOT_ERROR_CODES = {
    "STALE_STATE",
    "ROOM_STATE_CONFLICT",
    "HERO_ALREADY_LOCKED",
    "REMATCH_ALREADY_CONFIRMED",
    "ACTION_REJECTED",
}


class Clock:
    """可控时钟：过期断言不依赖真实时间。"""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, **delta) -> None:
        self._now = self._now + timedelta(**delta)


def make_app(tmp_path, clock: Clock, *, seed: int = 1):
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DATABASE": str(tmp_path / "contract.sqlite3"),
            "ONLINE_NOW": clock,
            "ONLINE_RNG_FACTORY": lambda: random.Random(seed),
            "ONLINE_ROOM_TTL": TTL,
        }
    )


def seat_pair(app):
    return app.test_client(), app.test_client()


def create_room(client, nickname="小王"):
    return client.post("/api/rooms", json={"nickname": nickname}).get_json()


def join_room(client, room_code, nickname="小李"):
    return client.post(
        "/api/rooms/join", json={"room_code": room_code, "nickname": nickname}
    ).get_json()


def get_room(client, room_id):
    return client.get(f"/api/rooms/{room_id}").get_json()


def lock_hero(client, room_id, hero_key, revision):
    return client.post(
        f"/api/rooms/{room_id}/hero",
        json={"hero_key": hero_key, "revision": revision},
    ).get_json()


def play_card(client, room_id, card_id, revision):
    return client.post(
        f"/api/rooms/{room_id}/actions/card",
        json={"card_id": card_id, "revision": revision},
    ).get_json()


def respond(client, room_id, action, revision):
    return client.post(
        f"/api/rooms/{room_id}/actions/respond",
        json={"action": action, "revision": revision},
    ).get_json()


def end_turn(client, room_id, revision):
    return client.post(
        f"/api/rooms/{room_id}/actions/end-turn", json={"revision": revision}
    ).get_json()


def rematch(client, room_id, revision):
    return client.post(
        f"/api/rooms/{room_id}/rematch", json={"revision": revision}
    ).get_json()


def forge_token(app, room_id, raw_token):
    """伪造"本浏览器持有该房间某凭证"的会话，用于触发 403 而非 401。"""
    client = app.test_client()
    with client.session_transaction() as session:
        session["online_tokens"] = {room_id: raw_token}
    return client


def open_match(app, a, b, *, hero_a="warrior", hero_b="ranger"):
    """A 建房、B 加入、双方锁定；返回 (room_id, 最后一份快照)。"""
    created = create_room(a, "小王")
    room_id = created["data"]["room"]["room_id"]
    join_room(b, created["data"]["room"]["room_code"], "小李")
    lock_hero(a, room_id, hero_a, 1)
    sealed = lock_hero(b, room_id, hero_b, 2)
    assert sealed["ok"] is True, sealed["error"]
    return room_id, sealed["data"]


def drive_to_finish(a, b, room_id):
    """双方都只结束回合、不出牌，直到打满回合上限结算。"""
    snapshot = get_room(a, room_id)["data"]
    for _ in range(30):
        if snapshot["room"]["status"] == "FINISHED":
            return snapshot
        revision = snapshot["room"]["revision"]
        view_a = get_room(a, room_id)["data"]
        if view_a["battle"]["available_actions"]["end_turn"]:
            payload = end_turn(a, room_id, revision)
        elif view_a["battle"]["response"]["active"]:
            payload = respond(a, room_id, "pass", revision)
        else:
            view_b = get_room(b, room_id)["data"]
            if view_b["battle"]["available_actions"]["end_turn"]:
                payload = end_turn(b, room_id, revision)
            else:
                payload = respond(b, room_id, "pass", revision)
        assert payload["ok"] is True, payload["error"]
        snapshot = payload["data"]
    return snapshot


# --------------------------------------------------------------------------
# 断言助手
# --------------------------------------------------------------------------


def assert_envelope(payload, *, ok):
    assert set(payload) == ENVELOPE_KEYS
    assert payload["ok"] is ok
    if ok:
        assert payload["error"] is None
        assert isinstance(payload["data"], dict)
    else:
        assert set(payload["error"]) == ERROR_KEYS
        assert payload["error"]["code"] == payload["error"]["code"].upper()
        assert payload["error"]["message"]


def assert_room_block(room):
    assert set(room) == ROOM_KEYS
    for key in ROOM_KEYS:
        assert room[key] is not None, key
    assert room["status"] in ROOM_STATUSES
    assert isinstance(room["revision"], int) and not isinstance(room["revision"], bool)
    assert room["revision"] >= 0
    assert isinstance(room["match_number"], int) and room["match_number"] >= 1
    for key in ("created_at", "updated_at", "expires_at"):
        datetime.fromisoformat(room[key])
    # 邀请链接只含 room_code，绝不携带座位凭证原文。
    assert room["invite_url"] == f"/join?room_code={room['room_code']}"


def assert_you_block(you, *, locked):
    assert set(you) == YOU_KEYS
    assert isinstance(you["nickname"], str) and you["nickname"]
    assert isinstance(you["hero_locked"], bool)
    assert you["hero_locked"] is locked
    assert isinstance(you["rematch_confirmed"], bool)


def assert_opponent_block(opponent):
    assert set(opponent) == OPPONENT_KEYS
    assert "hero_key" not in opponent
    assert opponent["joined"] is True
    assert isinstance(opponent["nickname"], str) and opponent["nickname"]
    assert isinstance(opponent["hero_locked"], bool)
    assert isinstance(opponent["rematch_confirmed"], bool)


def assert_rematch_block(block):
    assert set(block) == REMATCH_KEYS
    assert block["status"] in REMATCH_STATUSES
    assert block["requested_by"] in {"you", "opponent", None}


def assert_snapshot_shape(snapshot):
    assert set(snapshot) == {"room", "you", "opponent", "battle", "rematch"}
    assert_room_block(snapshot["room"])
    assert_you_block(snapshot["you"], locked=snapshot["you"]["hero_locked"])
    assert_rematch_block(snapshot["rematch"])
    if snapshot["room"]["status"] == "WAITING":
        assert snapshot["opponent"] is None
    else:
        assert_opponent_block(snapshot["opponent"])
    if snapshot["room"]["status"] in {"WAITING", "HERO_SELECT"}:
        assert snapshot["battle"] is None
    else:
        assert_battle_shape(snapshot["battle"])


def assert_side_shape(side):
    """公开字段必须齐全；手牌与意图由 assert_hand_isolation 单独按视角核对。"""
    assert SIDE_KEYS <= set(side)
    assert set(side["hero"]) == HERO_KEYS
    assert set(side["skill"]) == SKILL_KEYS
    assert set(side["equipment"]) == EQUIPMENT_KEYS


def assert_battle_shape(battle):
    assert set(battle) == BATTLE_KEYS
    assert battle["mode"] == "pvp"
    assert battle["phase"] in PVP_PHASES
    assert battle["viewer"] in {"player", "enemy"}
    assert set(battle["available_actions"]) == ACTIONS_KEYS
    assert set(battle["available_actions"]["respond"]) == RESPOND_KEYS
    assert set(battle["response"]) == RESPONSE_KEYS
    assert battle["enemy"]["intent"] is None
    for key in ("play_card", "use_skill", "end_turn"):
        assert isinstance(battle["available_actions"][key], bool)
    for key in RESPOND_KEYS:
        assert isinstance(battle["available_actions"]["respond"][key], bool)
    if battle["result"] is not None:
        assert set(battle["result"]) == RESULT_KEYS


def assert_hand_isolation(battle):
    """手牌只挂在自己一侧；对手侧必须"字段缺失"，不能用空数组顶替。

    意图字段则相反——它恒定挂在 enemy 一侧（在线恒为 None）。
    """
    viewer = battle["viewer"]
    other = "enemy" if viewer == "player" else "player"
    assert "hand" in battle[viewer]
    assert "hand" not in battle[other]
    assert "intent" in battle["enemy"]
    assert "intent" not in battle["player"]
    for card in battle[viewer]["hand"]:
        assert set(card) == HAND_CARD_KEYS


def assert_no_store(response):
    assert response.headers.get("Cache-Control") == "no-store"


# --------------------------------------------------------------------------
# §2.1 统一信封与缓存头
# --------------------------------------------------------------------------


def test_success_and_failure_share_the_frozen_envelope(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, _ = seat_pair(app)

    created = a.post("/api/rooms", json={"nickname": "小王"})
    body = created.get_json()
    assert created.status_code == 201
    assert_envelope(body, ok=True)
    assert_no_store(created)

    failed = a.post("/api/rooms/join", json={"room_code": "NOPE99", "nickname": "小李"})
    assert_envelope(failed.get_json(), ok=False)
    assert_no_store(failed)


def test_room_snapshot_top_level_shape_is_stable_across_states(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    created = create_room(a, "小王")
    room_id = created["data"]["room"]["room_id"]
    assert_snapshot_shape(created["data"])

    joined = join_room(b, created["data"]["room"]["room_code"], "小李")
    assert joined["data"]["room"]["status"] == "HERO_SELECT"
    assert_snapshot_shape(joined["data"])

    lock_hero(a, room_id, "warrior", 1)
    mid = get_room(b, room_id)["data"]
    assert_snapshot_shape(mid)

    sealed = lock_hero(b, room_id, "ranger", 2)["data"]
    assert sealed["room"]["status"] == "PLAYING"
    assert_snapshot_shape(sealed)


def test_playing_battle_matches_the_frozen_shape(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    room_id, _ = open_match(app, a, b)

    for client in (a, b):
        battle = get_room(client, room_id)["data"]["battle"]
        assert_battle_shape(battle)
        assert_hand_isolation(battle)
        assert_side_shape(battle["player"])
        assert_side_shape(battle["enemy"])


# --------------------------------------------------------------------------
# §6.1 错误码 → HTTP → data 映射
# --------------------------------------------------------------------------


def test_invalid_request_errors_carry_no_snapshot(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    room_id, _ = open_match(app, a, b)

    # 未定义字段 / 缺字段 / revision 类型非法，一律 400 且 data 为 null。
    cases = [
        a.post(f"/api/rooms/{room_id}/actions/end-turn", json={"revision": 3, "seat": "enemy"}),
        a.post(f"/api/rooms/{room_id}/actions/end-turn", json={}),
        a.post(f"/api/rooms/{room_id}/actions/end-turn", json={"revision": True}),
    ]
    for response in cases:
        assert response.status_code == 400
        assert response.get_json()["error"]["code"] == "INVALID_REQUEST"
        assert response.get_json()["data"] is None
    # 非 JSON 对象
    raw = a.post(f"/api/rooms/{room_id}/actions/end-turn", data="not json")
    assert raw.status_code == 400
    assert raw.get_json()["error"]["code"] == "INVALID_REQUEST"


def test_auth_and_forbidden_errors_carry_no_snapshot(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    room_id, _ = open_match(app, a, b)

    stranger = app.test_client()
    unauth = stranger.get(f"/api/rooms/{room_id}")
    assert unauth.status_code == 401
    assert unauth.get_json()["error"]["code"] == "ROOM_AUTH_REQUIRED"
    assert unauth.get_json()["data"] is None

    forged = forge_token(app, room_id, "forged-raw-token")
    denied = forged.get(f"/api/rooms/{room_id}")
    assert denied.status_code == 403
    assert denied.get_json()["error"]["code"] == "ROOM_FORBIDDEN"
    assert denied.get_json()["data"] is None


def test_not_found_and_not_joinable_errors_carry_no_snapshot(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    created = create_room(a, "小王")
    room_code = created["data"]["room"]["room_code"]
    room_id = created["data"]["room"]["room_id"]

    # 未知邀请码 → 404，无需凭证。
    missing = join_room(app.test_client(), "NOPE99", "小张")
    assert missing["error"]["code"] == "ROOM_NOT_FOUND"
    assert missing["data"] is None

    # 房间仍处 WAITING：本浏览器已持该房座位，不能再加入同一房间。
    second_tab = app.test_client()
    second_tab.set_cookie("session", a.get_cookie("session").value, domain="localhost")
    again = join_room(second_tab, room_code, "小王")
    assert again["error"]["code"] == "ALREADY_IN_ROOM"
    assert again["data"] is None

    # 满员后第三方加入 → ROOM_NOT_JOINABLE。
    join_room(b, room_code, "小李")
    full = join_room(app.test_client(), room_code, "小张")
    assert full["error"]["code"] == "ROOM_NOT_JOINABLE"
    assert full["data"] is None

    assert get_room(a, room_id)["data"]["room"]["status"] == "HERO_SELECT"


def test_validation_errors_carry_no_snapshot(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    room_id, _ = open_match(app, a, b)

    bad_nickname = a.post("/api/rooms", json={"nickname": "   "})
    assert bad_nickname.status_code == 422
    assert bad_nickname.get_json()["error"]["code"] == "INVALID_NICKNAME"
    assert bad_nickname.get_json()["data"] is None

    bad_hero = lock_hero(a, room_id, "not-a-hero", 3)
    assert bad_hero["error"]["code"] == "INVALID_HERO"


def test_snapshot_errors_carry_the_latest_room_snapshot(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    created = create_room(a, "小王")
    room_id = created["data"]["room"]["room_id"]
    join_room(b, created["data"]["room"]["room_code"], "小李")

    # HERO_ALREADY_LOCKED：同一座位用当前 revision 二次锁定。
    lock_hero(a, room_id, "warrior", 1)
    dup = lock_hero(a, room_id, "mage", 2)
    assert dup["error"]["code"] == "HERO_ALREADY_LOCKED"
    assert_snapshot_shape(dup["data"])

    # ROOM_STATE_CONFLICT：双方锁定后（PLAYING）用当前 revision 再锁英雄。
    lock_hero(b, room_id, "ranger", 2)
    conflict = lock_hero(a, room_id, "mage", 3)
    assert conflict["error"]["code"] == "ROOM_STATE_CONFLICT"
    assert_snapshot_shape(conflict["data"])

    # STALE_STATE：REMATCH 用旧 revision（版本比较先于规则校验）。
    finished = drive_to_finish(a, b, room_id)
    stale = rematch(a, room_id, finished["room"]["revision"] - 1)
    assert stale["error"]["code"] == "STALE_STATE"
    assert_snapshot_shape(stale["data"])


def test_action_rejected_carries_the_latest_snapshot(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    room_id, sealed = open_match(app, a, b)
    starting = sealed["battle"]["starting_side"]
    off_turn = b if starting == "player" else a
    revision = sealed["room"]["revision"]

    rejected = end_turn(off_turn, room_id, revision)
    assert rejected["error"]["code"] == "ACTION_REJECTED"
    assert_snapshot_shape(rejected["data"])
    # 规则拒绝不改变版本。
    assert rejected["data"]["room"]["revision"] == revision


def test_error_status_map_matches_the_frozen_table(tmp_path):
    """契约 §6.1 的 14 码 → HTTP 表；表里有的码实现都必须用对应状态码。"""
    assert ROOM_ERROR_STATUS == {
        "INVALID_REQUEST": 400,
        "ROOM_AUTH_REQUIRED": 401,
        "ROOM_FORBIDDEN": 403,
        "ROOM_NOT_FOUND": 404,
        "ALREADY_IN_ROOM": 409,
        "ROOM_NOT_JOINABLE": 409,
        "STALE_STATE": 409,
        "ROOM_STATE_CONFLICT": 409,
        "ROOM_EXPIRED": 410,
        "INVALID_NICKNAME": 422,
        "INVALID_HERO": 422,
        "HERO_ALREADY_LOCKED": 422,
        "REMATCH_ALREADY_CONFIRMED": 422,
        "ACTION_REJECTED": 422,
    }
    assert SNAPSHOT_ERROR_CODES <= set(ROOM_ERROR_STATUS)


# --------------------------------------------------------------------------
# §6.2 revision 乐观并发
# --------------------------------------------------------------------------


def test_revision_starts_at_zero_and_bumps_once_per_successful_write(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)

    created = create_room(a, "小王")
    assert created["data"]["room"]["revision"] == 0
    room_id = created["data"]["room"]["room_id"]

    joined = join_room(b, created["data"]["room"]["room_code"], "小李")
    assert joined["data"]["room"]["revision"] == 1

    first = lock_hero(a, room_id, "warrior", 1)
    assert first["data"]["room"]["revision"] == 2

    # 只读 GET 不推进版本。
    assert get_room(a, room_id)["data"]["room"]["revision"] == 2

    sealed = lock_hero(b, room_id, "ranger", 2)
    assert sealed["data"]["room"]["revision"] == 3


def test_same_revision_can_only_win_once(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    created = create_room(a, "小王")
    room_id = created["data"]["room"]["room_id"]
    join_room(b, created["data"]["room"]["room_code"], "小李")
    lock_hero(a, room_id, "warrior", 1)

    winner = lock_hero(b, room_id, "ranger", 2)
    assert winner["ok"] is True
    assert winner["data"]["room"]["revision"] == 3

    loser = lock_hero(a, room_id, "mage", 2)
    assert loser["error"]["code"] == "STALE_STATE"
    assert loser["data"]["room"]["revision"] == 3


# --------------------------------------------------------------------------
# §2.2 / §4 盲选与凭证保密
# --------------------------------------------------------------------------


def test_blind_pick_never_leaks_opponent_hero(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    created = create_room(a, "小王")
    room_id = created["data"]["room"]["room_id"]
    join_room(b, created["data"]["room"]["room_code"], "小李")
    lock_hero(a, room_id, "warrior", 1)

    view_b = get_room(b, room_id)["data"]
    assert view_b["opponent"]["hero_locked"] is True
    assert view_b["battle"] is None
    serialized = json.dumps(view_b, ensure_ascii=False)
    assert "warrior" not in serialized
    assert HEROES["warrior"].name not in serialized
    assert "hero_key" not in view_b["opponent"]


def test_snapshot_never_exposes_tokens_or_cookies(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    room_id, sealed = open_match(app, a, b)

    raw_a = a.get_cookie("session").value
    serialized = json.dumps(sealed, ensure_ascii=False)
    assert raw_a not in serialized
    assert "raw_token" not in serialized
    assert "online_tokens" not in serialized


# --------------------------------------------------------------------------
# §5 端点与 §7 双浏览器标准序列
# --------------------------------------------------------------------------


def test_full_standard_sequence_is_contract_clean(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)

    created = create_room(a, "小王")
    assert created["data"]["room"]["status"] == "WAITING"
    room_id = created["data"]["room"]["room_id"]

    joined = join_room(b, created["data"]["room"]["room_code"], "小李")
    assert joined["data"]["room"]["status"] == "HERO_SELECT"

    # 交叉视角：双方各自看到的 you / opponent 互换。
    view_a = get_room(a, room_id)["data"]
    view_b = get_room(b, room_id)["data"]
    assert view_a["you"]["nickname"] == "小王"
    assert view_a["opponent"]["nickname"] == "小李"
    assert view_b["you"]["nickname"] == "小李"
    assert view_b["opponent"]["nickname"] == "小王"

    lock_hero(a, room_id, "warrior", 1)
    sealed = lock_hero(b, room_id, "ranger", 2)
    assert sealed["data"]["room"]["status"] == "PLAYING"
    assert_battle_shape(sealed["data"]["battle"])
    assert_hand_isolation(sealed["data"]["battle"])


def test_rematch_flow_matches_the_frozen_shape(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    room_id, _ = open_match(app, a, b)
    finished = drive_to_finish(a, b, room_id)
    revision = finished["room"]["revision"]

    first = rematch(a, room_id, revision)
    assert first["ok"] is True
    assert_rematch_block(first["data"]["rematch"])
    assert first["data"]["rematch"]["status"] == "WAITING_CONFIRMATION"
    assert first["data"]["rematch"]["requested_by"] == "you"

    dup = rematch(a, room_id, first["data"]["room"]["revision"])
    assert dup["error"]["code"] == "REMATCH_ALREADY_CONFIRMED"
    assert_snapshot_shape(dup["data"])

    second = rematch(b, room_id, first["data"]["room"]["revision"])
    assert second["ok"] is True
    assert second["data"]["room"]["status"] == "HERO_SELECT"
    assert second["data"]["room"]["match_number"] == 2
    assert second["data"]["battle"] is None
    assert second["data"]["rematch"]["status"] == "NOT_AVAILABLE"


def test_expired_room_reports_410_without_a_snapshot(tmp_path):
    clock = Clock(START)
    app = make_app(tmp_path, clock)
    a, b = seat_pair(app)
    room_id, _ = open_match(app, a, b)

    clock.advance(hours=3)
    read = a.get(f"/api/rooms/{room_id}")
    assert read.status_code == 410
    assert read.get_json()["error"]["code"] == "ROOM_EXPIRED"
    assert read.get_json()["data"] is None

    acted = end_turn(a, room_id, 3)
    assert acted["error"]["code"] == "ROOM_EXPIRED"
    assert acted["data"] is None
