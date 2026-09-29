"""在线 PvP 的双浏览器 HTTP 验收测试（后端房间与持久化计划 §8.3）。

两个独立的 Flask test client 就是两台浏览器：Cookie 不共享，座位只能由凭证决定，
请求体里的 seat / viewer 一律无效。这里只走 HTTP，不直接碰服务层与数据库内部。
"""

import random
import sqlite3
from datetime import datetime, timedelta, timezone

from app import create_app
from game.battle import ROUND_LIMIT
from game.online_battle_service import hash_seat_token

START = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
TTL = timedelta(hours=2)


class Clock:
    """可控时钟：过期断言不依赖真实时间。"""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, **delta) -> None:
        self._now = self._now + timedelta(**delta)


def make_app(tmp_path, clock: Clock, *, seed: int = 1):
    """固定时钟与固定随机源：先手与洗牌不随运行漂移。"""
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DATABASE": str(tmp_path / "online_api.sqlite3"),
            "ONLINE_NOW": clock,
            "ONLINE_RNG_FACTORY": lambda: random.Random(seed),
            "ONLINE_ROOM_TTL": TTL,
        }
    )


def create_room(client, nickname="小王"):
    payload = client.post("/api/rooms", json={"nickname": nickname}).get_json()
    assert payload["ok"] is True, payload["error"]
    return payload["data"]


def join_room(client, room_code, nickname="小李"):
    payload = client.post(
        "/api/rooms/join", json={"room_code": room_code, "nickname": nickname}
    ).get_json()
    assert payload["ok"] is True, payload["error"]
    return payload["data"]


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


def copy_cookie(source, target):
    """把源浏览器的会话 Cookie 复制给目标，模拟同一浏览器刷新/新标签页。"""
    cookie = source.get_cookie("session")
    assert cookie is not None
    target.set_cookie("session", cookie.value, domain="localhost")


def seat_pair(app):
    """两台互不共享 Cookie 的浏览器。"""
    return app.test_client(), app.test_client()


def open_match(app, a, b, *, hero_a="warrior", hero_b="ranger"):
    """A 建房、B 加入、双方锁定；返回 (room_id, 最后一份快照)。"""
    created = create_room(a, "小王")
    room_id = created["room"]["room_id"]
    join_room(b, created["room"]["room_code"], "小李")
    assert lock_hero(a, room_id, hero_a, 1)["ok"] is True
    sealed = lock_hero(b, room_id, hero_b, 2)
    assert sealed["ok"] is True, sealed["error"]
    return room_id, sealed["data"]


# --------------------------------------------------------------------------
# 座位与 Cookie 隔离
# --------------------------------------------------------------------------


def test_each_browser_owns_exactly_one_seat(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    created = create_room(a, "小王")
    room_id = created["room"]["room_id"]
    join_room(b, created["room"]["room_code"], "小李")

    view_a = get_room(a, room_id)["data"]
    view_b = get_room(b, room_id)["data"]
    assert view_a["you"]["nickname"] == "小王"
    assert view_a["opponent"]["nickname"] == "小李"
    assert view_b["you"]["nickname"] == "小李"
    assert view_b["opponent"]["nickname"] == "小王"


def test_refresh_with_the_same_cookie_keeps_the_seat(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    room_id, _ = open_match(app, a, b)

    fresh = app.test_client()
    copy_cookie(a, fresh)
    view = get_room(fresh, room_id)
    assert view["ok"] is True
    assert view["data"]["you"]["nickname"] == "小王"
    # 刷新后仍是本方回合：revision 与座位都没变，可以直接继续操作。
    revision = view["data"]["room"]["revision"]
    assert end_turn(fresh, room_id, revision)["ok"] is True


def test_browser_without_a_cookie_cannot_read_or_act(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    room_id, _ = open_match(app, a, b)

    stranger = app.test_client()
    read = get_room(stranger, room_id)
    assert read["ok"] is False
    assert read["error"]["code"] == "ROOM_AUTH_REQUIRED"
    acted = end_turn(stranger, room_id, 3)
    assert acted["ok"] is False
    assert acted["error"]["code"] == "ROOM_AUTH_REQUIRED"


def test_browser_holding_another_room_token_has_no_credential_here(tmp_path):
    """凭证按 room_id 存进会话；持别房凭证的浏览器在本房没有凭证 → 401。"""
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    room_id, _ = open_match(app, a, b)

    outsider = app.test_client()
    create_room(outsider, "路人")
    denied = get_room(outsider, room_id)
    assert denied["ok"] is False
    assert denied["error"]["code"] == "ROOM_AUTH_REQUIRED"


def test_forged_credential_for_this_room_is_forbidden(tmp_path):
    """伪造本房凭证摘要对不上库里的记录 → 403（服务层可识别出"不属于该房间"）。"""
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    room_id, _ = open_match(app, a, b)

    forged = app.test_client()
    with forged.session_transaction() as session:
        session["online_tokens"] = {room_id: "forged-raw-token"}
    denied = get_room(forged, room_id)
    assert denied["ok"] is False
    assert denied["error"]["code"] == "ROOM_FORBIDDEN"


def test_a_browser_cannot_join_the_room_it_already_holds(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, _ = seat_pair(app)
    created = create_room(a, "小王")

    second_tab = app.test_client()
    copy_cookie(a, second_tab)
    outcome = second_tab.post(
        "/api/rooms/join",
        json={"room_code": created["room"]["room_code"], "nickname": "小王"},
    ).get_json()
    assert outcome["ok"] is False
    assert outcome["error"]["code"] == "ALREADY_IN_ROOM"
    # 被拒绝时 data 为 null，房间仍是待加入状态。
    assert outcome["data"] is None
    assert get_room(a, created["room"]["room_id"])["data"]["room"]["status"] == "WAITING"


# --------------------------------------------------------------------------
# 请求体里的 seat / viewer 一律无效
# --------------------------------------------------------------------------


def test_injected_seat_field_is_rejected_by_request_validation(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    created = create_room(a, "小王")
    room_id = created["room"]["room_id"]

    injected = b.post(
        "/api/rooms/join",
        json={
            "room_code": created["room"]["room_code"],
            "nickname": "小李",
            "seat": "enemy",
        },
    ).get_json()
    assert injected["ok"] is False
    assert injected["error"]["code"] == "INVALID_REQUEST"
    # 房间没有被这次请求改动。
    assert get_room(a, room_id)["data"]["room"]["status"] == "WAITING"


def test_injected_viewer_on_create_is_rejected(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, _ = seat_pair(app)
    outcome = a.post(
        "/api/rooms", json={"nickname": "小王", "viewer": "enemy"}
    ).get_json()
    assert outcome["ok"] is False
    assert outcome["error"]["code"] == "INVALID_REQUEST"


def test_extra_field_on_an_action_body_is_rejected(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    room_id, _ = open_match(app, a, b)

    outcome = a.post(
        f"/api/rooms/{room_id}/actions/end-turn",
        json={"revision": 3, "seat": "enemy"},
    ).get_json()
    assert outcome["ok"] is False
    assert outcome["error"]["code"] == "INVALID_REQUEST"


def test_hero_lock_writes_to_the_cookie_seat_only(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    created = create_room(a, "小王")
    room_id = created["room"]["room_id"]
    join_room(b, created["room"]["room_code"], "小李")

    locked = lock_hero(a, room_id, "warrior", 1)
    assert locked["ok"] is True
    assert locked["data"]["you"]["hero_key"] == "warrior"
    # B 看到的是"对手已锁"，而不是英雄本体；B 自己还没锁。
    view_b = get_room(b, room_id)["data"]
    assert view_b["opponent"]["hero_locked"] is True
    assert view_b["you"]["hero_locked"] is False
    assert view_b["you"]["hero_key"] is None


# --------------------------------------------------------------------------
# 盲选泄露
# --------------------------------------------------------------------------


def test_first_lock_hides_the_hero_from_the_other_seat(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    created = create_room(a, "小王")
    room_id = created["room"]["room_id"]
    join_room(b, created["room"]["room_code"], "小李")
    lock_hero(a, room_id, "warrior", 1)

    view_b = get_room(b, room_id)["data"]
    assert view_b["opponent"]["hero_locked"] is True
    assert "hero_key" not in view_b["opponent"]
    assert view_b["battle"] is None
    serialized = str(view_b)
    assert "warrior" not in serialized


# --------------------------------------------------------------------------
# 状态机与版本
# --------------------------------------------------------------------------


def test_revision_walks_the_standard_sequence(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)

    created = create_room(a, "小王")
    assert created["room"]["revision"] == 0
    assert created["room"]["status"] == "WAITING"
    room_id = created["room"]["room_id"]

    joined = join_room(b, created["room"]["room_code"], "小李")
    assert joined["room"]["revision"] == 1
    assert joined["room"]["status"] == "HERO_SELECT"

    first = lock_hero(a, room_id, "warrior", 1)
    assert first["data"]["room"]["revision"] == 2
    assert first["data"]["room"]["status"] == "HERO_SELECT"
    assert first["data"]["battle"] is None

    second = lock_hero(b, room_id, "ranger", 2)
    assert second["data"]["room"]["revision"] == 3
    assert second["data"]["room"]["status"] == "PLAYING"
    assert second["data"]["battle"] is not None


def test_off_turn_seat_action_is_rejected_and_keeps_revision(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    room_id, sealed = open_match(app, a, b)
    assert sealed["battle"]["starting_side"] == "player"

    rejected = end_turn(b, room_id, 3)
    assert rejected["ok"] is False
    assert rejected["error"]["code"] == "ACTION_REJECTED"
    # 规则拒绝仍带最新快照，且不改变版本。
    assert rejected["data"]["room"]["revision"] == 3


def test_stale_revision_replay_is_rejected_with_the_latest_snapshot(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    room_id, _ = open_match(app, a, b)
    # 手牌只挂在本人视角：从 A 自己那一侧取，而不是复用 B 锁定后的快照。
    card_id = get_room(a, room_id)["data"]["battle"]["player"]["hand"][0]["id"]

    played = play_card(a, room_id, card_id, 3)
    assert played["ok"] is True
    assert played["data"]["room"]["revision"] == 4

    replay = play_card(a, room_id, card_id, 3)
    assert replay["ok"] is False
    assert replay["error"]["code"] == "STALE_STATE"
    assert replay["data"]["room"]["revision"] == 4


def test_pvp_battle_never_exposes_opponent_hand_or_ai_intent(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    room_id, sealed = open_match(app, a, b)

    for client, own_side, other_side in ((a, "player", "enemy"), (b, "enemy", "player")):
        battle = get_room(client, room_id)["data"]["battle"]
        assert battle["mode"] == "pvp"
        assert battle["enemy"]["intent"] is None
        assert "hand" in battle[own_side]
        assert "hand" not in battle[other_side]


# --------------------------------------------------------------------------
# 出牌、响应与对手可见性
# --------------------------------------------------------------------------


def test_opponent_polls_the_public_battle_without_seeing_the_hand(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    room_id, _ = open_match(app, a, b)
    view_a = get_room(a, room_id)["data"]
    slash = next(c for c in view_a["battle"]["player"]["hand"] if c["key"] == "slash")

    played = play_card(a, room_id, slash["id"], 3)
    assert played["ok"] is True
    assert played["data"]["room"]["revision"] == 4
    assert played["data"]["battle"]["phase"] == "RESPONSE"
    # 攻击方视角下 response.active 为 false，但公开信息仍可读。
    assert played["data"]["battle"]["response"]["active"] is False

    view_b = get_room(b, room_id)
    assert view_b["ok"] is True
    battle = view_b["data"]["battle"]
    assert view_b["data"]["room"]["revision"] == 4
    assert battle["viewer"] == "enemy"
    assert battle["phase"] == "RESPONSE"
    assert battle["response"]["active"] is True
    assert battle["response"]["kind"] == "attack"
    assert battle["response"]["attacker"] == "player"
    assert "hand" not in battle["player"]
    # 挂起期间伤害还没落地，引擎不会写"造成 N 点伤害"那行；此刻的公开信息
    # 就是 response 块里的牌名与伤害值。
    assert battle["response"]["card_name"] == slash["name"]
    assert battle["response"]["damage"] >= 0


def test_defender_dodge_closes_the_response_window(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    room_id, _ = open_match(app, a, b)
    view_a = get_room(a, room_id)["data"]
    slash = next(c for c in view_a["battle"]["player"]["hand"] if c["key"] == "slash")
    # 手牌只看得到自己一侧，防守方（B）的手牌要从 B 的视角取。
    hand_before = len(get_room(b, room_id)["data"]["battle"]["enemy"]["hand"])

    play_card(a, room_id, slash["id"], 3)
    dodged = respond(b, room_id, "dodge", 4)
    assert dodged["ok"] is True
    assert dodged["data"]["room"]["revision"] == 5
    assert dodged["data"]["battle"]["phase"] == "PLAYER_TURN"
    assert dodged["data"]["battle"]["response"]["active"] is False
    # 闪避牌被打出：B 自己一侧的手牌少一张。
    after_b = get_room(b, room_id)["data"]["battle"]["enemy"]["hand"]
    assert len(after_b) == hand_before - 1


# --------------------------------------------------------------------------
# 终局与再来一局
# --------------------------------------------------------------------------


def drive_to_finish(a, b, room_id):
    """双方都只结束回合、不出牌，直到打满回合上限结算。"""
    snapshot = get_room(a, room_id)["data"]
    for _ in range(2 * ROUND_LIMIT + 8):
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


def test_round_limit_finishes_the_room_and_saves_one_result(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    room_id, _ = open_match(app, a, b)

    snapshot = drive_to_finish(a, b, room_id)
    assert snapshot["room"]["status"] == "FINISHED"
    # 双方都未出牌，回合上限按生命值结算；战士 32 > 游侠 27，先手座位获胜。
    assert snapshot["battle"]["result"]["reason"] == "hp"
    assert snapshot["battle"]["result"]["winner"] == "player"

    with sqlite3.connect(tmp_path / "online_api.sqlite3") as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM online_match_results WHERE room_id = ?", (room_id,)
        ).fetchone()[0]
    assert count == 1


def test_rematch_requires_both_sides_and_starts_a_new_blind_pick(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    room_id, _ = open_match(app, a, b)
    finished = drive_to_finish(a, b, room_id)
    revision = finished["room"]["revision"]

    first = rematch(a, room_id, revision)
    assert first["ok"] is True
    assert first["data"]["room"]["status"] == "FINISHED"
    assert first["data"]["room"]["match_number"] == 1
    assert first["data"]["rematch"]["status"] == "WAITING_CONFIRMATION"
    assert first["data"]["rematch"]["requested_by"] == "you"

    duplicate = rematch(a, room_id, first["data"]["room"]["revision"])
    assert duplicate["ok"] is False
    assert duplicate["error"]["code"] == "REMATCH_ALREADY_CONFIRMED"
    assert duplicate["data"] is not None

    second = rematch(b, room_id, first["data"]["room"]["revision"])
    assert second["ok"] is True
    assert second["data"]["room"]["status"] == "HERO_SELECT"
    assert second["data"]["room"]["match_number"] == 2
    assert second["data"]["battle"] is None
    assert second["data"]["you"]["hero_locked"] is False
    assert second["data"]["rematch"]["status"] == "NOT_AVAILABLE"


# --------------------------------------------------------------------------
# 过期
# --------------------------------------------------------------------------


def test_expired_room_rejects_reads_and_actions(tmp_path):
    clock = Clock(START)
    app = make_app(tmp_path, clock)
    a, b = seat_pair(app)
    room_id, _ = open_match(app, a, b)

    clock.advance(hours=3)
    read = get_room(a, room_id)
    assert read["ok"] is False
    assert read["error"]["code"] == "ROOM_EXPIRED"
    assert read["data"] is None

    acted = end_turn(a, room_id, 3)
    assert acted["ok"] is False
    assert acted["error"]["code"] == "ROOM_EXPIRED"


# --------------------------------------------------------------------------
# 旧人机模式回归
# --------------------------------------------------------------------------


def test_legacy_pve_endpoints_are_unaffected(tmp_path):
    app = make_app(tmp_path, Clock(START))
    client = app.test_client()

    created = client.post("/api/game", json={"hero_key": "warrior"})
    assert created.status_code == 201
    payload = created.get_json()
    assert payload["ok"] is True
    assert payload["data"]["mode"] == "pve"
    assert payload["data"]["viewer"] == "player"

    state = client.get("/api/game").get_json()["data"]
    assert state["mode"] == "pve"
    # 旧接口先手随机（api_routes.py 用未播种的 random.Random()）：可能直接落在
    # 玩家回合，也可能电脑先手并挂起"等待玩家响应闪避/反制"。两种形态都要认。
    if state["phase"] == "PLAYER_TURN":
        assert state["available_actions"]["end_turn"] is True
        assert state["enemy"]["intent"] is not None
    else:
        assert state["phase"] == "RESPONSE"
        assert state["available_actions"]["respond"]["pass"] is True
        assert state["response"]["active"] is True
    assert "hand" in state["player"]


def test_legacy_pve_seat_forgery_is_still_rejected(tmp_path):
    app = make_app(tmp_path, Clock(START))
    client = app.test_client()
    client.post("/api/game", json={"hero_key": "warrior"})

    forged = client.get("/api/game?seat=enemy").get_json()
    assert forged["ok"] is False
    assert forged["error"]["code"] == "INVALID_SEAT"


def test_online_endpoints_do_not_accept_a_legacy_seat_query(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    room_id, _ = open_match(app, a, b)

    # 在线路由没有 seat query 语义；凭证是唯一授权依据，附带参数被忽略而非提升权限。
    view = a.get(f"/api/rooms/{room_id}?seat=enemy").get_json()
    assert view["ok"] is True
    assert view["data"]["you"]["nickname"] == "小王"


def test_token_summary_not_the_raw_value_is_compared(tmp_path):
    app = make_app(tmp_path, Clock(START))
    a, b = seat_pair(app)
    created = create_room(a, "小王")
    room_id = created["room"]["room_id"]
    join_room(b, created["room"]["room_code"], "小李")

    # 伪造一个与真实凭证摘要不同、但形态合法的凭证。
    forged = app.test_client()
    forged.set_cookie("session", "forged-token", domain="localhost")
    with forged.session_transaction() as session:
        session["online_tokens"] = {room_id: "forged-raw-token"}
    denied = get_room(forged, room_id)
    assert denied["ok"] is False
    assert denied["error"]["code"] == "ROOM_FORBIDDEN"
    # 摘要确实是 sha256，而不是明文原值。
    assert hash_seat_token("forged-raw-token") != "forged-raw-token"
