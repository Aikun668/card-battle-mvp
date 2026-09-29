"""在线 PvP 房间的持久化边界。

本模块是唯一直接读写在线三张表（`online_rooms` / `online_room_players` /
`online_match_results`）的地方：房间记录、座位凭证摘要、revision 比较并交换、
惰性过期与结算结果的幂等写入。它不认识 Flask 请求，也不拼装 HTTP 响应。

所有写操作都在 `BEGIN IMMEDIATE` 事务内完成；每次成功改变可见状态的写入严格
把 revision 加一；规则拒绝、版本冲突和过期幂等判定都不重复写库。
"""

import json
import random
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Sequence

from game.battle import PVP_MODE, BattleState
from game.models import ActionResult, Side
from game.public_state import public_battle_state

STATUS_WAITING = "WAITING"
STATUS_HERO_SELECT = "HERO_SELECT"
STATUS_PLAYING = "PLAYING"
STATUS_FINISHED = "FINISHED"
STATUS_EXPIRED = "EXPIRED"

SEAT_PLAYER = "player"
SEAT_ENEMY = "enemy"

# 邀请码去掉 0/O/1/I 这类易混字符，方便口头或手抄传递。
_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_CODE_LENGTH = 6
_CODE_RETRY_LIMIT = 8

_ROOM_COLUMNS = (
    "room_id, room_code, status, match_number, revision, battle_state_json, "
    "result_saved_match_number, created_at, updated_at, expires_at"
)

_OUTCOME_MESSAGES = {
    "ROOM_NOT_FOUND": "房间不存在或已失效",
    "ROOM_FORBIDDEN": "座位凭证不属于该房间",
    "ROOM_AUTH_REQUIRED": "需要有效的座位凭证",
    "ROOM_EXPIRED": "房间已过期，请重新创建",
    "ROOM_NOT_JOINABLE": "房间已满、已开局、已结束或已过期",
    "ALREADY_IN_ROOM": "该浏览器已加入此房间",
    "STALE_STATE": "房间状态已更新，请基于最新快照重试",
    "ROOM_STATE_CONFLICT": "当前房间状态不允许该操作",
    "ACTION_REJECTED": "动作被战斗规则拒绝",
    "INVALID_NICKNAME": "昵称不合法",
    "INVALID_HERO": "英雄不存在",
    "HERO_ALREADY_LOCKED": "本局你已锁定英雄",
    "REMATCH_ALREADY_CONFIRMED": "本局你已确认再来一局",
}


@dataclass(frozen=True)
class PlayerRecord:
    """一个座位的持久化记录；`token_hash` 是凭证摘要，不是可用凭证。"""

    seat: str
    nickname: str
    token_hash: str
    selected_hero_key: str | None
    rematch_confirmed_for: int | None
    joined_at: str


@dataclass
class RoomRecord:
    """房间的完整快照；`battle_state` 是已解析的 `BattleState.to_dict()` 数据。"""

    room_id: str
    room_code: str
    status: str
    match_number: int
    revision: int
    battle_state: dict | None
    result_saved_match_number: int | None
    created_at: str
    updated_at: str
    expires_at: str
    players: dict[str, PlayerRecord] = field(default_factory=dict)

    @property
    def player(self) -> PlayerRecord | None:
        return self.players.get(SEAT_PLAYER)

    @property
    def enemy(self) -> PlayerRecord | None:
        return self.players.get(SEAT_ENEMY)

    @property
    def expires_at_value(self) -> datetime:
        return _parse_iso(self.expires_at)

    def seat_of(self, token_hash: str) -> str | None:
        """按凭证摘要反查座位；没有匹配返回 None。"""
        for seat in (SEAT_PLAYER, SEAT_ENEMY):
            record = self.players.get(seat)
            if record is not None and secrets.compare_digest(
                record.token_hash, token_hash
            ):
                return seat
        return None


@dataclass
class RoomOutcome:
    """存储原语的统一返回：成功时带最新房间记录，失败时带契约错误码。"""

    ok: bool
    code: str | None = None
    message: str | None = None
    room: RoomRecord | None = None
    seat: str | None = None


def message_for(code: str) -> str:
    """错误码对应的中文完整句；未知码原样返回，避免响应里出现空消息。"""
    return _OUTCOME_MESSAGES.get(code, code)


def _failure(code: str, *, room: RoomRecord | None = None, seat: str | None = None):
    return RoomOutcome(
        ok=False, code=code, message=message_for(code), room=room, seat=seat
    )


def _parse_iso(value: str) -> datetime:
    """历史数据可能没带时区；一律按 UTC 解读，避免比较时抛异常。"""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def default_build_battle(player_hero_key: str, enemy_hero_key: str) -> dict:
    """双方锁定后创建一局 PvP 战斗；先手、初始能量与阶段全由引擎决定。"""
    state = BattleState.create(
        player_hero_key,
        random.Random(),
        mode=PVP_MODE,
        opponent_hero_key=enemy_hero_key,
    )
    return state.to_dict()


class OnlineRoomStore:
    """在线房间的 SQLite 持久化原语；不处理授权策略，只比较凭证摘要。"""

    def __init__(
        self,
        database_path: str,
        *,
        now: Callable[[], datetime],
        room_ttl: timedelta | None = None,
    ) -> None:
        self._database_path = str(database_path)
        self._now = now
        # 传入 TTL 后，每次成功改变房间状态的写入都会顺延过期时间；不传则房间
        # 只在创建时给定 expires_at（仓储测试就用这种固定过期语义）。
        self._ttl = room_ttl

    @property
    def now(self) -> Callable[[], datetime]:
        return self._now

    @property
    def room_ttl(self) -> timedelta | None:
        """续期用的房间有效期；服务层据此生成创建时的 expires_at，保持两处一致。"""
        return self._ttl

    # ------------------------------------------------------------------
    # 基础设施
    # ------------------------------------------------------------------

    @contextmanager
    def _conn(self):
        """一个写事务：自动 BEGIN IMMEDIATE，异常回滚，正常提交。"""
        connection = sqlite3.connect(
            self._database_path, timeout=5.0, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except Exception:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        else:
            connection.execute("COMMIT")
        finally:
            connection.close()

    def _read(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _now_value(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    def _now_str(self) -> str:
        return _to_iso(self._now_value())

    def _renew_str(self) -> str | None:
        """按 TTL 顺延后的新过期时刻；未配置 TTL 时返回 None（固定过期语义）。"""
        if self._ttl is None:
            return None
        return _to_iso(self._now_value() + self._ttl)

    def _write(
        self,
        connection,
        room_id: str,
        now_str: str,
        columns: dict | None = None,
        expressions: Sequence[str] = (),
    ) -> None:
        """可见状态写入的统一出口：额外列 + revision + 1 + updated_at，并按需续期。

        过期标记不经过这里——到期是房间的终点，不该被顺延。
        """
        assignments = [f"{name} = ?" for name in (columns or {})]
        params = list((columns or {}).values())
        assignments.extend(expressions)
        assignments.append("revision = revision + 1")
        assignments.append("updated_at = ?")
        params.append(now_str)
        expires_str = self._renew_str()
        if expires_str is not None:
            assignments.append("expires_at = ?")
            params.append(expires_str)
        params.append(room_id)
        connection.execute(
            f"UPDATE online_rooms SET {', '.join(assignments)} WHERE room_id = ?",
            params,
        )

    # ------------------------------------------------------------------
    # 读取辅助
    # ------------------------------------------------------------------

    def _room_from_rows(self, room_row, player_rows) -> RoomRecord:
        battle_state = None
        if room_row["battle_state_json"] is not None:
            battle_state = json.loads(room_row["battle_state_json"])
        players = {
            row["seat"]: PlayerRecord(
                seat=row["seat"],
                nickname=row["nickname"],
                token_hash=row["token_hash"],
                selected_hero_key=row["selected_hero_key"],
                rematch_confirmed_for=row["rematch_confirmed_for"],
                joined_at=row["joined_at"],
            )
            for row in player_rows
        }
        return RoomRecord(
            room_id=room_row["room_id"],
            room_code=room_row["room_code"],
            status=room_row["status"],
            match_number=room_row["match_number"],
            revision=room_row["revision"],
            battle_state=battle_state,
            result_saved_match_number=room_row["result_saved_match_number"],
            created_at=room_row["created_at"],
            updated_at=room_row["updated_at"],
            expires_at=room_row["expires_at"],
            players=players,
        )

    def _load(self, connection, room_id: str) -> RoomRecord | None:
        room_row = connection.execute(
            f"SELECT {_ROOM_COLUMNS} FROM online_rooms WHERE room_id = ?",
            (room_id,),
        ).fetchone()
        if room_row is None:
            return None
        player_rows = connection.execute(
            "SELECT seat, nickname, token_hash, selected_hero_key, "
            "rematch_confirmed_for, joined_at FROM online_room_players "
            "WHERE room_id = ? ORDER BY seat",
            (room_id,),
        ).fetchall()
        return self._room_from_rows(room_row, player_rows)

    def _load_by_code(self, connection, room_code: str) -> RoomRecord | None:
        room_row = connection.execute(
            f"SELECT {_ROOM_COLUMNS} FROM online_rooms WHERE room_code = ?",
            (room_code,),
        ).fetchone()
        if room_row is None:
            return None
        return self._load(connection, room_row["room_id"])

    def _fetch(self, room_id: str) -> RoomRecord | None:
        connection = self._read()
        try:
            return self._load(connection, room_id)
        finally:
            connection.close()

    # ------------------------------------------------------------------
    # 过期
    # ------------------------------------------------------------------

    def _expire_in_conn(self, connection, room: RoomRecord) -> RoomRecord:
        """把已到期的房间原子标为 EXPIRED 并加一版；已过期则是空操作。"""
        if room.status == STATUS_EXPIRED:
            return room
        connection.execute(
            "UPDATE online_rooms SET status = ?, revision = revision + 1, updated_at = ? "
            "WHERE room_id = ? AND status != ?",
            (STATUS_EXPIRED, self._now_str(), room.room_id, STATUS_EXPIRED),
        )
        return self._load(connection, room.room_id)

    def _expire_if_due(self, connection, room: RoomRecord) -> tuple[RoomRecord, bool]:
        if room.status == STATUS_EXPIRED:
            return room, True
        if room.expires_at_value <= self._now_value():
            return self._expire_in_conn(connection, room), True
        return room, False

    # ------------------------------------------------------------------
    # 原语
    # ------------------------------------------------------------------

    def create_room(
        self, player_nickname: str, token_hash: str, expires_at: datetime
    ) -> RoomOutcome:
        now_str = self._now_str()
        expires_str = _to_iso(expires_at)
        for _ in range(_CODE_RETRY_LIMIT):
            room_id = "r_" + secrets.token_urlsafe(12)
            room_code = _new_code()
            try:
                with self._conn() as connection:
                    connection.execute(
                        "INSERT INTO online_rooms (room_id, room_code, status, "
                        "match_number, revision, battle_state_json, "
                        "result_saved_match_number, created_at, updated_at, expires_at) "
                        "VALUES (?, ?, ?, 1, 0, NULL, NULL, ?, ?, ?)",
                        (room_id, room_code, STATUS_WAITING, now_str, now_str, expires_str),
                    )
                    connection.execute(
                        "INSERT INTO online_room_players (room_id, seat, nickname, "
                        "token_hash, selected_hero_key, rematch_confirmed_for, joined_at) "
                        "VALUES (?, ?, ?, ?, NULL, NULL, ?)",
                        (room_id, SEAT_PLAYER, player_nickname, token_hash, now_str),
                    )
            except sqlite3.IntegrityError:
                # 极低概率的码/ID 冲突：换一个再试，不把数据库异常暴露出去。
                continue
            return RoomOutcome(ok=True, room=self._fetch(room_id), seat=SEAT_PLAYER)
        return _failure("ROOM_STATE_CONFLICT")

    def join_waiting_room(
        self,
        room_code: str,
        enemy_nickname: str,
        token_hash: str,
        *,
        known_token_hashes: Sequence[str] = (),
    ) -> RoomOutcome:
        """占用待加入房间的 enemy 座位。

        `known_token_hashes` 是该浏览器已持有的全部凭证摘要（含本次新生成的
        候选摘要）；只要其中任意一个已属于此房间，就按契约拒绝，避免同一浏览器
        用两个标签页自我对战。这一判定与座位写入必须同处一个写事务才安全。
        """
        with self._conn() as connection:
            room = self._load_by_code(connection, room_code)
            if room is None:
                return _failure("ROOM_NOT_FOUND")
            room, expired = self._expire_if_due(connection, room)
            if expired:
                return _failure("ROOM_NOT_JOINABLE", room=room)
            if room.status != STATUS_WAITING or room.enemy is not None:
                return _failure("ROOM_NOT_JOINABLE", room=room)
            if _room_holds_any_token(room, known_token_hashes):
                return _failure("ALREADY_IN_ROOM", room=room)
            now_str = self._now_str()
            connection.execute(
                "INSERT INTO online_room_players (room_id, seat, nickname, token_hash, "
                "selected_hero_key, rematch_confirmed_for, joined_at) "
                "VALUES (?, ?, ?, ?, NULL, NULL, ?)",
                (room.room_id, SEAT_ENEMY, enemy_nickname, token_hash, now_str),
            )
            self._write(connection, room.room_id, now_str, {"status": STATUS_HERO_SELECT})
            return RoomOutcome(
                ok=True,
                room=self._load(connection, room.room_id),
                seat=SEAT_ENEMY,
            )

    def load_authorized_room(self, room_id: str, token_hash: str) -> RoomOutcome:
        if not token_hash:
            return _failure("ROOM_AUTH_REQUIRED")
        with self._conn() as connection:
            room = self._load(connection, room_id)
            if room is None:
                return _failure("ROOM_NOT_FOUND")
            seat = room.seat_of(token_hash)
            if seat is None:
                return _failure("ROOM_FORBIDDEN")
            room, expired = self._expire_if_due(connection, room)
            if expired:
                return _failure("ROOM_EXPIRED", room=room, seat=seat)
            return RoomOutcome(ok=True, room=room, seat=seat)

    def lock_hero(
        self,
        room_id: str,
        seat: str,
        hero_key: str,
        expected_revision: int,
        *,
        build_battle: Callable[[str, str], dict] | None = None,
    ) -> RoomOutcome:
        with self._conn() as connection:
            room = self._load(connection, room_id)
            if room is None:
                return _failure("ROOM_NOT_FOUND")
            room, expired = self._expire_if_due(connection, room)
            if expired:
                return _failure("ROOM_EXPIRED", room=room, seat=seat)
            # 先比版本再比状态：旧版本的重放一律得到 STALE_STATE，前端据此复位，
            # 而不是被误报成"当前状态不允许该操作"。
            if room.revision != expected_revision:
                return _failure("STALE_STATE", room=room, seat=seat)
            if room.status != STATUS_HERO_SELECT:
                return _failure("ROOM_STATE_CONFLICT", room=room, seat=seat)
            record = room.players.get(seat)
            if record is None:
                return _failure("ROOM_FORBIDDEN", room=room, seat=seat)
            if record.selected_hero_key is not None:
                return _failure("HERO_ALREADY_LOCKED", room=room, seat=seat)

            now_str = self._now_str()
            connection.execute(
                "UPDATE online_room_players SET selected_hero_key = ? "
                "WHERE room_id = ? AND seat = ?",
                (hero_key, room_id, seat),
            )
            locked = self._load(connection, room_id)
            player_key = locked.player.selected_hero_key if locked.player else None
            enemy_key = locked.enemy.selected_hero_key if locked.enemy else None
            if player_key is not None and enemy_key is not None:
                builder = build_battle or default_build_battle
                payload = builder(player_key, enemy_key)
                self._write(
                    connection,
                    room_id,
                    now_str,
                    {"status": STATUS_PLAYING, "battle_state_json": json.dumps(payload)},
                )
            else:
                self._write(connection, room_id, now_str)
            return RoomOutcome(
                ok=True, room=self._load(connection, room_id), seat=seat
            )

    def apply_battle_action(
        self,
        room_id: str,
        seat: str,
        expected_revision: int,
        mutate: Callable[[BattleState], ActionResult],
        *,
        describe_result: Callable[[BattleState], dict] | None = None,
    ) -> RoomOutcome:
        with self._conn() as connection:
            room = self._load(connection, room_id)
            if room is None:
                return _failure("ROOM_NOT_FOUND")
            room, expired = self._expire_if_due(connection, room)
            if expired:
                return _failure("ROOM_EXPIRED", room=room, seat=seat)
            if room.revision != expected_revision:
                return _failure("STALE_STATE", room=room, seat=seat)
            if room.status != STATUS_PLAYING or room.battle_state is None:
                return _failure("ROOM_STATE_CONFLICT", room=room, seat=seat)
            if seat not in room.players:
                return _failure("ROOM_FORBIDDEN", room=room, seat=seat)

            state = BattleState.from_dict(room.battle_state)
            outcome = mutate(state)
            if not outcome.ok:
                # 规则拒绝不写库、不加版本，只把当前快照交回给上层。
                return _failure("ACTION_REJECTED", room=room, seat=seat)

            now_str = self._now_str()
            payload = state.to_dict()
            if state.is_finished():
                describe = describe_result or self._describe_result
                self._save_result(connection, room, describe(state))
                self._write(
                    connection,
                    room_id,
                    now_str,
                    {
                        "status": STATUS_FINISHED,
                        "battle_state_json": json.dumps(payload),
                        "result_saved_match_number": room.match_number,
                    },
                )
            else:
                self._write(
                    connection,
                    room_id,
                    now_str,
                    {"battle_state_json": json.dumps(payload)},
                )
            return RoomOutcome(
                ok=True, room=self._load(connection, room_id), seat=seat
            )

    def confirm_rematch(
        self, room_id: str, seat: str, expected_revision: int
    ) -> RoomOutcome:
        with self._conn() as connection:
            room = self._load(connection, room_id)
            if room is None:
                return _failure("ROOM_NOT_FOUND")
            room, expired = self._expire_if_due(connection, room)
            if expired:
                return _failure("ROOM_EXPIRED", room=room, seat=seat)
            if room.status != STATUS_FINISHED:
                return _failure("ROOM_STATE_CONFLICT", room=room, seat=seat)
            if room.revision != expected_revision:
                return _failure("STALE_STATE", room=room, seat=seat)
            record = room.players.get(seat)
            if record is None:
                return _failure("ROOM_FORBIDDEN", room=room, seat=seat)
            if record.rematch_confirmed_for == room.match_number:
                return _failure("REMATCH_ALREADY_CONFIRMED", room=room, seat=seat)

            now_str = self._now_str()
            connection.execute(
                "UPDATE online_room_players SET rematch_confirmed_for = ? "
                "WHERE room_id = ? AND seat = ?",
                (room.match_number, room_id, seat),
            )
            confirmed = self._load(connection, room_id)
            both = all(
                player is not None
                and player.rematch_confirmed_for == confirmed.match_number
                for player in (confirmed.player, confirmed.enemy)
            )
            if both:
                # 双方确认：清空上一局的战斗与英雄选择，回到新一局盲选。
                connection.execute(
                    "UPDATE online_room_players SET selected_hero_key = NULL, "
                    "rematch_confirmed_for = NULL WHERE room_id = ?",
                    (room_id,),
                )
                self._write(
                    connection,
                    room_id,
                    now_str,
                    {"status": STATUS_HERO_SELECT, "battle_state_json": None},
                    ("match_number = match_number + 1",),
                )
            else:
                self._write(connection, room_id, now_str)
            return RoomOutcome(
                ok=True, room=self._load(connection, room_id), seat=seat
            )

    def mark_expired_if_due(self, room_id: str) -> RoomOutcome:
        with self._conn() as connection:
            room = self._load(connection, room_id)
            if room is None:
                return _failure("ROOM_NOT_FOUND")
            room, _ = self._expire_if_due(connection, room)
            return RoomOutcome(ok=True, room=room)

    # ------------------------------------------------------------------
    # 结算
    # ------------------------------------------------------------------

    def _describe_result(self, state: BattleState) -> dict:
        """默认结算口径：胜负原因复用公开战斗状态的规则结论，不另写一套。"""
        public = public_battle_state(state, Side.PLAYER)
        result = public["result"] or {}
        return {
            "player_hero_key": state.participants[Side.PLAYER].hero.key,
            "enemy_hero_key": state.participants[Side.ENEMY].hero.key,
            "winner": result.get("winner"),
            "result_reason": result.get("reason", "kill"),
            "turns": state.round_number,
            "finished_at": self._now_str(),
        }

    def _save_result(self, connection, room: RoomRecord, described: dict) -> None:
        """以 (room_id, match_number) 唯一约束保证幂等：重放不会写出第二条。"""
        connection.execute(
            "INSERT OR IGNORE INTO online_match_results "
            "(room_id, match_number, player_hero_key, enemy_hero_key, winner, "
            "result_reason, turns, finished_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                room.room_id,
                room.match_number,
                described["player_hero_key"],
                described["enemy_hero_key"],
                described["winner"],
                described["result_reason"],
                described["turns"],
                described["finished_at"],
            ),
        )


def _room_holds_any_token(room: RoomRecord, token_hashes: Sequence[str]) -> bool:
    """该房间是否已占用这批凭证摘要中的任意一个（用于拒绝同浏览器自我加入）。"""
    return any(
        room.seat_of(token_hash) is not None
        for token_hash in token_hashes
        if token_hash
    )


def _new_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


def _to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()
