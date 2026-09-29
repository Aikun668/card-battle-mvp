import random
import sqlite3
from datetime import datetime, timedelta, timezone

from game.battle import BattleState
from game.models import ActionResult, BattlePhase, Side
from game.online_rooms import OnlineRoomStore
from game.repository import init_db, save_match_result


class Clock:
    """可控时钟：过期与 updated_at 断言不依赖真实时间。"""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, **delta) -> None:
        self._now = self._now + timedelta(**delta)


START = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
TTL = timedelta(hours=2)


def make_store(tmp_path, clock: Clock | None = None) -> OnlineRoomStore:
    database_path = tmp_path / "online.sqlite3"
    init_db(str(database_path))
    return OnlineRoomStore(str(database_path), now=clock or Clock(START))


def build_pvp_battle(player_hero_key: str, enemy_hero_key: str) -> dict:
    """用真实引擎造一份可还原的 PvP 战斗 JSON；先手固定为 player 便于断言。"""
    state = BattleState.create(
        player_hero_key,
        random.Random(1),
        mode="pvp",
        opponent_hero_key=enemy_hero_key,
        starting_side=Side.PLAYER,
    )
    return state.to_dict()


def open_room(store: OnlineRoomStore, clock: Clock):
    """创建 + 加入 + 双方锁定，得到一间进入 PLAYING 的房间。"""
    room = store.create_room("小王", "hash-a", clock() + TTL).room
    room = store.join_waiting_room(room.room_code, "小李", "hash-b").room
    room = store.lock_hero(
        room.room_id, "player", "warrior", room.revision
    ).room
    outcome = store.lock_hero(
        room.room_id,
        "enemy",
        "mage",
        room.revision,
        build_battle=build_pvp_battle,
    )
    return outcome


def _stored_battle_json(tmp_path, room_id: str) -> str:
    """直接读库里保存的战斗 JSON，用来断言持久化内容而非反序列化对象。"""
    with sqlite3.connect(tmp_path / "online.sqlite3") as connection:
        return connection.execute(
            "SELECT battle_state_json FROM online_rooms WHERE room_id = ?",
            (room_id,),
        ).fetchone()[0]


# --------------------------------------------------------------------------
# schema 与旧表
# --------------------------------------------------------------------------


def test_init_db_is_repeatable_and_keeps_match_results(tmp_path):
    database_path = tmp_path / "card_battle.sqlite3"
    init_db(str(database_path))
    init_db(str(database_path))  # 重复执行不得报错
    save_match_result(str(database_path), "warrior", "VICTORY", 4)
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT hero_key, outcome, turns FROM match_results"
        ).fetchone()
        tables = {
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert row == ("warrior", "VICTORY", 4)
    assert {"online_rooms", "online_room_players", "online_match_results"} <= tables


def test_room_code_and_room_id_are_unique_constraints(tmp_path):
    store = make_store(tmp_path)
    clock = Clock(START)
    with sqlite3.connect(tmp_path / "online.sqlite3") as connection:
        indexes = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='online_rooms'"
        ).fetchone()[0]
    assert "UNIQUE" in indexes.upper()
    room = store.create_room("小王", "hash-a", clock() + TTL).room
    with sqlite3.connect(tmp_path / "online.sqlite3") as connection:
        connection.execute(
            "INSERT INTO online_rooms "
            "(room_id, room_code, status, match_number, revision, created_at, updated_at, expires_at) "
            "VALUES (?, ?, 'WAITING', 1, 0, 'x', 'x', 'x')",
            ("r_dup", "CODE-UNIQUE-1"),
        )
        try:
            # 复用已存在的 room_id，应触发唯一约束。
            connection.execute(
                "INSERT INTO online_rooms "
                "(room_id, room_code, status, match_number, revision, created_at, updated_at, expires_at) "
                "VALUES (?, ?, 'WAITING', 1, 0, 'x', 'x', 'x')",
                (room.room_id, "CODE-DUP"),
            )
        except sqlite3.IntegrityError:
            raised = True
        else:
            raised = False
    assert raised


# --------------------------------------------------------------------------
# 创建与加入
# --------------------------------------------------------------------------


def test_create_room_starts_waiting_with_one_player_seat(tmp_path):
    store = make_store(tmp_path)
    clock = Clock(START)
    outcome = store.create_room("小王", "hash-a", clock() + TTL)
    assert outcome.ok is True
    room = outcome.room
    assert room.status == "WAITING"
    assert room.revision == 0
    assert room.match_number == 1
    assert room.battle_state is None
    assert room.result_saved_match_number is None
    assert set(room.players) == {"player"}
    player = room.players["player"]
    assert player.nickname == "小王"
    assert player.token_hash == "hash-a"
    assert player.selected_hero_key is None
    assert player.rematch_confirmed_for is None


def test_two_rooms_get_distinct_ids_and_codes(tmp_path):
    store = make_store(tmp_path)
    clock = Clock(START)
    first = store.create_room("A", "ha", clock() + TTL).room
    second = store.create_room("B", "hb", clock() + TTL).room
    assert first.room_id != second.room_id
    assert first.room_code != second.room_code


def test_join_promotes_room_to_hero_select_and_seats_enemy(tmp_path):
    store = make_store(tmp_path)
    clock = Clock(START)
    room = store.create_room("小王", "hash-a", clock() + TTL).room
    outcome = store.join_waiting_room(room.room_code, "小李", "hash-b")
    assert outcome.ok is True
    assert outcome.seat == "enemy"
    joined = outcome.room
    assert joined.status == "HERO_SELECT"
    assert joined.revision == room.revision + 1
    assert set(joined.players) == {"player", "enemy"}
    assert joined.players["enemy"].token_hash == "hash-b"
    assert joined.players["player"].selected_hero_key is None
    assert joined.players["enemy"].selected_hero_key is None


def test_second_join_is_rejected(tmp_path):
    store = make_store(tmp_path)
    clock = Clock(START)
    room = store.create_room("小王", "hash-a", clock() + TTL).room
    store.join_waiting_room(room.room_code, "小李", "hash-b")
    again = store.join_waiting_room(room.room_code, "小张", "hash-c")
    assert again.ok is False
    assert again.code == "ROOM_NOT_JOINABLE"


# --------------------------------------------------------------------------
# 授权
# --------------------------------------------------------------------------


def test_load_authorized_room_maps_token_hash_to_seat(tmp_path):
    store = make_store(tmp_path)
    clock = Clock(START)
    room = store.create_room("小王", "hash-a", clock() + TTL).room
    store.join_waiting_room(room.room_code, "小李", "hash-b")

    player_view = store.load_authorized_room(room.room_id, "hash-a")
    enemy_view = store.load_authorized_room(room.room_id, "hash-b")
    assert player_view.ok is True and player_view.seat == "player"
    assert enemy_view.ok is True and enemy_view.seat == "enemy"


def test_load_authorized_room_rejects_wrong_token_and_unknown_room(tmp_path):
    store = make_store(tmp_path)
    clock = Clock(START)
    room = store.create_room("小王", "hash-a", clock() + TTL).room

    forbidden = store.load_authorized_room(room.room_id, "hash-x")
    assert forbidden.ok is False and forbidden.code == "ROOM_FORBIDDEN"

    missing = store.load_authorized_room("r_nope", "hash-a")
    assert missing.ok is False and missing.code == "ROOM_NOT_FOUND"


# --------------------------------------------------------------------------
# 锁定英雄与战斗创建
# --------------------------------------------------------------------------


def test_first_lock_stays_in_hero_select_and_hides_hero(tmp_path):
    store = make_store(tmp_path)
    clock = Clock(START)
    room = store.create_room("小王", "hash-a", clock() + TTL).room
    room = store.join_waiting_room(room.room_code, "小李", "hash-b").room

    outcome = store.lock_hero(room.room_id, "player", "warrior", room.revision)
    assert outcome.ok is True
    locked = outcome.room
    assert locked.status == "HERO_SELECT"
    assert locked.revision == room.revision + 1
    assert locked.players["player"].selected_hero_key == "warrior"
    assert locked.players["enemy"].selected_hero_key is None
    assert locked.battle_state is None


def test_second_lock_creates_battle_and_enters_playing(tmp_path):
    store = make_store(tmp_path)
    clock = Clock(START)
    room = store.create_room("小王", "hash-a", clock() + TTL).room
    room = store.join_waiting_room(room.room_code, "小李", "hash-b").room
    room = store.lock_hero(room.room_id, "player", "warrior", room.revision).room

    outcome = store.lock_hero(
        room.room_id, "enemy", "mage", room.revision, build_battle=build_pvp_battle
    )
    assert outcome.ok is True
    playing = outcome.room
    assert playing.status == "PLAYING"
    assert playing.revision == room.revision + 1
    assert playing.battle_state is not None
    assert playing.battle_state["mode"] == "pvp"
    assert (
        playing.battle_state["participants"]["player"]["hero_key"] == "warrior"
    )
    assert playing.battle_state["participants"]["enemy"]["hero_key"] == "mage"


def test_lock_hero_with_wrong_revision_is_stale(tmp_path):
    store = make_store(tmp_path)
    clock = Clock(START)
    room = store.create_room("小王", "hash-a", clock() + TTL).room
    room = store.join_waiting_room(room.room_code, "小李", "hash-b").room
    outcome = store.lock_hero(room.room_id, "player", "warrior", room.revision - 1)
    assert outcome.ok is False
    assert outcome.code == "STALE_STATE"
    assert outcome.room.revision == room.revision
    assert outcome.room.players["player"].selected_hero_key is None


# --------------------------------------------------------------------------
# 动作 CAS、规则拒绝与终局
# --------------------------------------------------------------------------


def test_action_success_bumps_revision_once(tmp_path):
    store = make_store(tmp_path)
    clock = Clock(START)
    playing = open_room(store, clock).room
    before = playing.battle_state

    def bump_round(state: BattleState) -> ActionResult:
        state.round_number += 1
        return ActionResult(True, "")

    outcome = store.apply_battle_action(
        playing.room_id, "player", playing.revision, bump_round
    )
    assert outcome.ok is True
    assert outcome.room.revision == playing.revision + 1
    assert outcome.room.battle_state["round_number"] == before["round_number"] + 1
    assert outcome.room.status == "PLAYING"


def test_action_with_stale_revision_changes_nothing(tmp_path):
    store = make_store(tmp_path)
    clock = Clock(START)
    playing = open_room(store, clock).room
    original = _stored_battle_json(tmp_path, playing.room_id)

    store.apply_battle_action(
        playing.room_id,
        "player",
        playing.revision,
        lambda state: ActionResult(True, ""),
    )
    stale = store.apply_battle_action(
        playing.room_id,
        "player",
        playing.revision,  # 已被前一次写入消耗
        lambda state: ActionResult(True, ""),
    )
    assert stale.ok is False
    assert stale.code == "STALE_STATE"
    assert stale.room.revision == playing.revision + 1
    assert _stored_battle_json(tmp_path, playing.room_id) == original  # 战斗 JSON 只被改过一次


def test_rule_rejection_does_not_bump_revision(tmp_path):
    store = make_store(tmp_path)
    clock = Clock(START)
    playing = open_room(store, clock).room

    rejected = store.apply_battle_action(
        playing.room_id,
        "player",
        playing.revision,
        lambda state: ActionResult(False, "现在不是你的回合"),
    )
    assert rejected.ok is False
    assert rejected.code == "ACTION_REJECTED"
    assert rejected.room.revision == playing.revision


def test_terminal_action_finishes_room_and_saves_one_result(tmp_path):
    store = make_store(tmp_path)
    clock = Clock(START)
    playing = open_room(store, clock).room

    def kill(state: BattleState) -> ActionResult:
        state.participant(Side.ENEMY).combatant.hp = 0
        state.phase = BattlePhase.VICTORY
        return ActionResult(True, "")

    def describe(state: BattleState) -> dict:
        return {
            "player_hero_key": state.participants[Side.PLAYER].hero.key,
            "enemy_hero_key": state.participants[Side.ENEMY].hero.key,
            "winner": "player",
            "result_reason": "kill",
            "turns": state.round_number,
            "finished_at": clock().isoformat(),
        }

    outcome = store.apply_battle_action(
        playing.room_id, "player", playing.revision, kill, describe_result=describe
    )
    assert outcome.ok is True
    assert outcome.room.status == "FINISHED"
    assert outcome.room.revision == playing.revision + 1
    assert outcome.room.result_saved_match_number == 1

    with sqlite3.connect(tmp_path / "online.sqlite3") as connection:
        rows = connection.execute(
            "SELECT player_hero_key, enemy_hero_key, winner, result_reason "
            "FROM online_match_results WHERE room_id = ?",
            (playing.room_id,),
        ).fetchall()
    assert rows == [("warrior", "mage", "player", "kill")]

    # 用同一旧 revision 重放：只能得到 STALE_STATE，不产生第二条结果。
    retry = store.apply_battle_action(
        playing.room_id, "player", playing.revision, kill, describe_result=describe
    )
    assert retry.ok is False and retry.code == "STALE_STATE"
    with sqlite3.connect(tmp_path / "online.sqlite3") as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM online_match_results WHERE room_id = ?",
            (playing.room_id,),
        ).fetchone()[0]
    assert count == 1


# --------------------------------------------------------------------------
# 过期
# --------------------------------------------------------------------------


def test_lazy_expiry_marks_room_once(tmp_path):
    clock = Clock(START)
    store = OnlineRoomStore(str(tmp_path / "online.sqlite3"), now=clock)
    init_db(str(tmp_path / "online.sqlite3"))
    store = OnlineRoomStore(str(tmp_path / "online.sqlite3"), now=clock)
    room = store.create_room("小王", "hash-a", clock() + TTL).room

    clock.advance(hours=3)
    first = store.load_authorized_room(room.room_id, "hash-a")
    assert first.ok is False and first.code == "ROOM_EXPIRED"
    assert first.room.status == "EXPIRED"
    assert first.room.revision == room.revision + 1

    second = store.load_authorized_room(room.room_id, "hash-a")
    assert second.ok is False and second.code == "ROOM_EXPIRED"
    assert second.room.revision == room.revision + 1  # 幂等，不再递增


def test_expiry_before_due_is_a_noop(tmp_path):
    store = make_store(tmp_path)
    clock = Clock(START)
    room = store.create_room("小王", "hash-a", clock() + TTL).room
    outcome = store.mark_expired_if_due(room.room_id)
    assert outcome.room.status == "WAITING"
    assert outcome.room.revision == room.revision
