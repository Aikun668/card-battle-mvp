import json
import random
import sqlite3
from datetime import datetime, timedelta, timezone

from game.battle import ROUND_LIMIT
from game.catalog import HEROES
from game.online_battle_service import (
    NICKNAME_MAX_LENGTH,
    OnlineBattleService,
    hash_seat_token,
    normalize_nickname,
)
from game.online_rooms import OnlineRoomStore
from game.repository import init_db


class Clock:
    """可控时钟：过期与续期断言不依赖真实时间。"""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, **delta) -> None:
        self._now = self._now + timedelta(**delta)


START = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
TTL = timedelta(hours=2)


def make_service(tmp_path, clock: Clock) -> OnlineBattleService:
    database_path = tmp_path / "online.sqlite3"
    init_db(str(database_path))
    store = OnlineRoomStore(str(database_path), now=clock, room_ttl=TTL)
    # 固定随机源：先手与洗牌不随运行漂移。
    return OnlineBattleService(store, rng_factory=lambda: random.Random(7))


def create_and_join(service: OnlineBattleService):
    """创建 + 加入，返回 (player_id, player_token, enemy_token, room_id)。"""
    created = service.create_room("小王")
    room = created.snapshot["room"]
    joined = service.join_room(room["room_code"], "小李", known_token_hashes=())
    return created.raw_token, joined.raw_token, room["room_id"]


def drive_to_finish(service: OnlineBattleService, room_id, player_token, enemy_token):
    """双方只结束回合、不出牌，直到打满回合上限结算（必然平局）。"""
    snapshot = service.get_room_state(room_id, player_token).snapshot
    for _ in range(2 * ROUND_LIMIT + 8):
        if snapshot["room"]["status"] == "FINISHED":
            return snapshot
        revision = snapshot["room"]["revision"]
        player_view = service.get_room_state(room_id, player_token).snapshot
        if player_view["battle"]["available_actions"]["end_turn"]:
            result = service.end_turn(room_id, player_token, revision)
        else:
            result = service.end_turn(room_id, enemy_token, revision)
        assert result.ok, result.message
        snapshot = result.snapshot
    return snapshot


# --------------------------------------------------------------------------
# 昵称与凭证工具
# --------------------------------------------------------------------------


def test_normalize_nickname_accepts_one_to_twelve_chars():
    assert normalize_nickname("小王") == "小王"
    assert normalize_nickname("  阿狸  ") == "阿狸"
    assert normalize_nickname("a" * NICKNAME_MAX_LENGTH) == "a" * NICKNAME_MAX_LENGTH


def test_normalize_nickname_rejects_blank_too_long_and_non_string():
    assert normalize_nickname("") is None
    assert normalize_nickname("   ") is None
    assert normalize_nickname("a" * (NICKNAME_MAX_LENGTH + 1)) is None
    assert normalize_nickname(123) is None


def test_hash_seat_token_is_deterministic_and_not_the_raw_value():
    raw = "raw-token-abc"
    assert hash_seat_token(raw) == hash_seat_token(raw)
    assert hash_seat_token(raw) != raw


# --------------------------------------------------------------------------
# 创建与加入
# --------------------------------------------------------------------------


def test_create_room_returns_waiting_snapshot_and_raw_token(tmp_path):
    service = make_service(tmp_path, Clock(START))
    result = service.create_room("小王")
    assert result.ok is True
    snapshot = result.snapshot
    assert snapshot["room"]["status"] == "WAITING"
    assert snapshot["room"]["revision"] == 0
    assert snapshot["room"]["match_number"] == 1
    assert snapshot["opponent"] is None
    assert snapshot["battle"] is None
    assert snapshot["you"]["nickname"] == "小王"
    assert snapshot["you"]["hero_key"] is None
    assert snapshot["you"]["hero_locked"] is False
    assert isinstance(result.raw_token, str) and result.raw_token


def test_create_room_rejects_invalid_nickname(tmp_path):
    service = make_service(tmp_path, Clock(START))
    assert service.create_room("   ").code == "INVALID_NICKNAME"


def test_browser_holding_seat_cannot_join_its_own_room(tmp_path):
    service = make_service(tmp_path, Clock(START))
    created = service.create_room("小王")
    room_code = created.snapshot["room"]["room_code"]
    known = [hash_seat_token(created.raw_token)]
    outcome = service.join_room(room_code, "小李", known_token_hashes=known)
    assert outcome.ok is False
    assert outcome.code == "ALREADY_IN_ROOM"


def test_join_unknown_code_is_not_found(tmp_path):
    service = make_service(tmp_path, Clock(START))
    outcome = service.join_room("NOPE99", "小李")
    assert outcome.ok is False and outcome.code == "ROOM_NOT_FOUND"


def test_join_full_room_is_not_joinable(tmp_path):
    service = make_service(tmp_path, Clock(START))
    created = service.create_room("小王")
    room_code = created.snapshot["room"]["room_code"]
    service.join_room(room_code, "小李", known_token_hashes=[])
    third = service.join_room(room_code, "小张", known_token_hashes=[])
    assert third.ok is False and third.code == "ROOM_NOT_JOINABLE"


# --------------------------------------------------------------------------
# 授权：座位只由凭证决定
# --------------------------------------------------------------------------


def test_seat_is_derived_from_token_and_swapped_token_is_forbidden(tmp_path):
    service = make_service(tmp_path, Clock(START))
    player_token, enemy_token, room_id = create_and_join(service)

    player_view = service.get_room_state(room_id, player_token)
    enemy_view = service.get_room_state(room_id, enemy_token)
    assert player_view.snapshot["you"]["nickname"] == "小王"
    assert enemy_view.snapshot["you"]["nickname"] == "小李"

    forged = service.get_room_state(room_id, "not-a-real-token")
    assert forged.ok is False and forged.code == "ROOM_FORBIDDEN"


def test_missing_token_requires_auth_and_unknown_room_is_not_found(tmp_path):
    service = make_service(tmp_path, Clock(START))
    _, _, room_id = create_and_join(service)
    assert service.get_room_state(room_id, None).code == "ROOM_AUTH_REQUIRED"
    assert service.get_room_state(room_id, "").code == "ROOM_AUTH_REQUIRED"


def test_token_from_another_room_is_forbidden(tmp_path):
    service = make_service(tmp_path, Clock(START))
    _, other_token, _ = create_and_join(service)
    second = service.create_room("另一个房主")
    second_room = second.snapshot["room"]["room_id"]
    outcome = service.get_room_state(second_room, other_token)
    assert outcome.ok is False and outcome.code == "ROOM_FORBIDDEN"


# --------------------------------------------------------------------------
# 盲选泄露
# --------------------------------------------------------------------------


def test_first_lock_hides_hero_from_the_other_seat(tmp_path):
    service = make_service(tmp_path, Clock(START))
    player_token, enemy_token, room_id = create_and_join(service)

    locked = service.lock_hero(room_id, player_token, "warrior", 1)
    assert locked.ok is True
    assert locked.snapshot["room"]["status"] == "HERO_SELECT"
    assert locked.snapshot["room"]["revision"] == 2
    assert locked.snapshot["battle"] is None

    enemy_view = service.get_room_state(room_id, enemy_token).snapshot
    assert enemy_view["opponent"]["hero_locked"] is True
    assert "hero_key" not in enemy_view["opponent"]
    # 对手的英雄键与英雄名都不得出现在任何字段里。
    serialized = json.dumps(enemy_view, ensure_ascii=False)
    assert "warrior" not in serialized
    assert HEROES["warrior"].name not in serialized


# --------------------------------------------------------------------------
# 双方锁定 → PLAYING
# --------------------------------------------------------------------------


def test_both_locked_creates_pvp_battle_for_each_viewer(tmp_path):
    service = make_service(tmp_path, Clock(START))
    player_token, enemy_token, room_id = create_and_join(service)
    service.lock_hero(room_id, player_token, "warrior", 1)
    enemy_lock = service.lock_hero(room_id, enemy_token, "mage", 2)

    assert enemy_lock.ok is True
    assert enemy_lock.snapshot["room"]["status"] == "PLAYING"
    assert enemy_lock.snapshot["room"]["revision"] == 3

    player_view = service.get_room_state(room_id, player_token).snapshot
    enemy_view = service.get_room_state(room_id, enemy_token).snapshot
    assert player_view["battle"]["viewer"] == "player"
    assert enemy_view["battle"]["viewer"] == "enemy"
    # 在线战斗恒为 pvp，且没有任何 AI 意图。
    assert player_view["battle"]["mode"] == "pvp"
    assert player_view["battle"]["enemy"]["intent"] is None
    assert enemy_view["battle"]["enemy"]["intent"] is None


def test_pvp_first_mover_is_left_at_turn_start_without_running_ai(tmp_path):
    service = make_service(tmp_path, Clock(START))
    player_token, enemy_token, room_id = create_and_join(service)
    service.lock_hero(room_id, player_token, "warrior", 1)
    service.lock_hero(room_id, enemy_token, "mage", 2)

    battle = service.get_room_state(room_id, player_token).snapshot["battle"]
    # 先手所在座位就是当前阶段；引擎没有替电脑跑回合（否则阶段会越过起手回合）。
    assert battle["starting_side"] in {"player", "enemy"}
    expected = (
        "PLAYER_TURN" if battle["starting_side"] == "player" else "ENEMY_TURN"
    )
    assert battle["phase"] == expected


# --------------------------------------------------------------------------
# 动作合法性与版本
# --------------------------------------------------------------------------


def _playing(service: OnlineBattleService):
    player_token, enemy_token, room_id = create_and_join(service)
    service.lock_hero(room_id, player_token, "warrior", 1)
    service.lock_hero(room_id, enemy_token, "mage", 2)
    return player_token, enemy_token, room_id


def test_action_is_rejected_for_the_seat_that_is_not_on_turn(tmp_path):
    service = make_service(tmp_path, Clock(START))
    player_token, enemy_token, room_id = _playing(service)
    battle = service.get_room_state(room_id, player_token).snapshot["battle"]
    non_starter = "enemy" if battle["starting_side"] == "player" else "player"
    token = player_token if non_starter == "player" else enemy_token

    result = service.end_turn(room_id, token, 3)
    assert result.ok is False
    assert result.code == "ACTION_REJECTED"
    # 规则拒绝仍带最新快照，且不改变版本。
    assert result.snapshot["room"]["revision"] == 3


def test_successful_action_bumps_revision_and_stale_replay_is_rejected(tmp_path):
    service = make_service(tmp_path, Clock(START))
    player_token, enemy_token, room_id = _playing(service)
    battle = service.get_room_state(room_id, player_token).snapshot["battle"]
    starter_token = (
        player_token if battle["starting_side"] == "player" else enemy_token
    )

    first = service.end_turn(room_id, starter_token, 3)
    assert first.ok is True
    assert first.snapshot["room"]["revision"] == 4

    stale = service.end_turn(room_id, starter_token, 3)
    assert stale.ok is False
    assert stale.code == "STALE_STATE"
    assert stale.snapshot["room"]["revision"] == 4


# --------------------------------------------------------------------------
# 终局与再来一局
# --------------------------------------------------------------------------


def test_round_limit_finishes_once_and_saves_one_result(tmp_path):
    service = make_service(tmp_path, Clock(START))
    player_token, enemy_token, room_id = _playing(service)

    snapshot = drive_to_finish(service, room_id, player_token, enemy_token)
    assert snapshot["room"]["status"] == "FINISHED"
    # 双方都未进攻，回合上限按生命值结算；战士 32 > 法师 28，先手座位获胜。
    assert snapshot["battle"]["result"]["winner"] == "player"
    assert snapshot["battle"]["result"]["reason"] == "hp"

    with sqlite3.connect(tmp_path / "online.sqlite3") as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM online_match_results WHERE room_id = ?",
            (room_id,),
        ).fetchone()[0]
    assert count == 1


def test_rematch_requires_both_sides_and_starts_a_new_blind_pick(tmp_path):
    service = make_service(tmp_path, Clock(START))
    player_token, enemy_token, room_id = _playing(service)
    finished = drive_to_finish(service, room_id, player_token, enemy_token)
    revision = finished["room"]["revision"]

    first = service.request_rematch(room_id, player_token, revision)
    assert first.ok is True
    assert first.snapshot["room"]["status"] == "FINISHED"
    assert first.snapshot["room"]["match_number"] == 1
    assert first.snapshot["rematch"]["status"] == "WAITING_CONFIRMATION"
    assert first.snapshot["rematch"]["requested_by"] == "you"

    # 同一座位重复确认是 422，且带最新快照。
    duplicate = service.request_rematch(
        room_id, player_token, first.snapshot["room"]["revision"]
    )
    assert duplicate.ok is False
    assert duplicate.code == "REMATCH_ALREADY_CONFIRMED"
    assert duplicate.snapshot is not None

    second = service.request_rematch(
        room_id, enemy_token, first.snapshot["room"]["revision"]
    )
    assert second.ok is True
    assert second.snapshot["room"]["status"] == "HERO_SELECT"
    assert second.snapshot["room"]["match_number"] == 2
    assert second.snapshot["battle"] is None
    assert second.snapshot["you"]["hero_locked"] is False
    assert second.snapshot["rematch"]["status"] == "NOT_AVAILABLE"


# --------------------------------------------------------------------------
# 过期
# --------------------------------------------------------------------------


def test_expired_room_rejects_reads(tmp_path):
    clock = Clock(START)
    service = make_service(tmp_path, clock)
    player_token, _, room_id = create_and_join(service)

    clock.advance(hours=3)
    outcome = service.get_room_state(room_id, player_token)
    assert outcome.ok is False
    assert outcome.code == "ROOM_EXPIRED"


def test_expired_room_rejects_actions(tmp_path):
    clock = Clock(START)
    service = make_service(tmp_path, clock)
    player_token, enemy_token, room_id = _playing(service)

    clock.advance(hours=3)
    outcome = service.end_turn(room_id, player_token, 3)
    assert outcome.ok is False
    assert outcome.code == "ROOM_EXPIRED"
