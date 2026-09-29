"""在线 PvP 的业务编排层。

本模块把房间生命周期（创建 / 加入 / 盲选 / 对局 / 结算 / 再来一局）、座位凭证授权
和视图拼装串起来，只调用 `OnlineRoomStore` 的持久化原语与 `BattleState` 的规则方法，
既不写 SQL 也不构造 Flask 响应。

对外只暴露带错误码与最新快照的 `ServiceResult`：成功时快照恒为对象，失败时只有契约
规定要带快照的错误码才附上快照，路由层据此决定响应体的 `data`。
"""

import hashlib
import random
import secrets
from dataclasses import dataclass
from typing import Callable, Sequence

from game.battle import PVP_MODE, BattleState
from game.catalog import HEROES
from game.models import Side
from game.online_rooms import (
    SEAT_ENEMY,
    SEAT_PLAYER,
    STATUS_FINISHED,
    STATUS_PLAYING,
    STATUS_WAITING,
    OnlineRoomStore,
    RoomOutcome,
    RoomRecord,
    message_for,
)
from game.public_state import public_battle_state

NICKNAME_MAX_LENGTH = 12

# 失败时仍按契约（接口契约 §6.1 的 data 列）携带最新快照的错误码；其余失败
# 一律 data=null，不把半截状态喂给前端。
SNAPSHOT_ERROR_CODES = frozenset(
    {
        "STALE_STATE",
        "ROOM_STATE_CONFLICT",
        "HERO_ALREADY_LOCKED",
        "REMATCH_ALREADY_CONFIRMED",
        "ACTION_REJECTED",
    }
)

REMATCH_NOT_AVAILABLE = "NOT_AVAILABLE"
REMATCH_WAITING_CONFIRMATION = "WAITING_CONFIRMATION"

SIDE_BY_SEAT = {SEAT_PLAYER: Side.PLAYER, SEAT_ENEMY: Side.ENEMY}
OPPONENT_SEAT = {SEAT_PLAYER: SEAT_ENEMY, SEAT_ENEMY: SEAT_PLAYER}


def new_seat_token() -> str:
    """一个座位凭证原文；只在创建/加入响应中交给浏览器，不落库、不写日志。"""
    return secrets.token_urlsafe(32)


def hash_seat_token(raw_token: str) -> str:
    """座位凭证的单向摘要；数据库与比较都只用这个值。"""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def normalize_nickname(value: object) -> str | None:
    """去除首尾空白后返回 1–12 个 Unicode 字符的昵称；不合法返回 None。"""
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    if not 1 <= len(trimmed) <= NICKNAME_MAX_LENGTH:
        return None
    return trimmed


@dataclass(frozen=True)
class ServiceResult:
    """服务层统一返回；`snapshot` 已按请求者视角组装，路由层只负责序列化。"""

    ok: bool
    code: str | None = None
    message: str | None = None
    snapshot: dict | None = None
    raw_token: str | None = None


class OnlineBattleService:
    """房间流程与凭证授权的业务编排；不认识 HTTP，也不碰 SQL。"""

    def __init__(
        self,
        store: OnlineRoomStore,
        *,
        rng_factory: Callable[[], random.Random] | None = None,
        room_ttl=None,
    ) -> None:
        self._store = store
        # 未显式传入时复用存储层的有效期，避免创建与续期两处配置各写一个值。
        self._room_ttl = room_ttl if room_ttl is not None else store.room_ttl
        if self._room_ttl is None:
            raise ValueError("在线服务必须配置 room_ttl，否则房间创建即过期")
        self._rng_factory = rng_factory or random.Random

    @property
    def store(self) -> OnlineRoomStore:
        return self._store

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def create_room(self, nickname: object) -> ServiceResult:
        clean = normalize_nickname(nickname)
        if clean is None:
            return self._failure("INVALID_NICKNAME")
        raw_token = new_seat_token()
        expires_at = self._store.now() + self._room_ttl
        outcome = self._store.create_room(
            clean, hash_seat_token(raw_token), expires_at
        )
        if not outcome.ok:
            return self._failure(outcome.code or "ROOM_STATE_CONFLICT", outcome=outcome)
        return ServiceResult(
            ok=True,
            snapshot=self._snapshot(outcome.room, outcome.seat),
            raw_token=raw_token,
        )

    def join_room(
        self,
        room_code: object,
        nickname: object,
        *,
        known_token_hashes: Sequence[str] = (),
    ) -> ServiceResult:
        clean = normalize_nickname(nickname)
        if clean is None:
            return self._failure("INVALID_NICKNAME")
        if not isinstance(room_code, str) or not room_code.strip():
            return self._failure("ROOM_NOT_FOUND")
        raw_token = new_seat_token()
        outcome = self._store.join_waiting_room(
            room_code.strip(),
            clean,
            hash_seat_token(raw_token),
            known_token_hashes=known_token_hashes,
        )
        if not outcome.ok:
            return self._failure(outcome.code or "ROOM_NOT_JOINABLE", outcome=outcome)
        return ServiceResult(
            ok=True,
            snapshot=self._snapshot(outcome.room, outcome.seat),
            raw_token=raw_token,
        )

    def get_room_state(self, room_id: object, raw_token: str | None) -> ServiceResult:
        return self._from_outcome(self._authorize(room_id, raw_token))

    def lock_hero(
        self,
        room_id: object,
        raw_token: str | None,
        hero_key: object,
        revision: int,
    ) -> ServiceResult:
        auth = self._authorize(room_id, raw_token)
        if not auth.ok:
            return self._from_outcome(auth)
        if not isinstance(hero_key, str) or hero_key not in HEROES:
            return self._failure("INVALID_HERO")
        outcome = self._store.lock_hero(
            auth.room.room_id,
            auth.seat,
            hero_key,
            revision,
            build_battle=self._build_battle,
        )
        return self._from_outcome(outcome)

    # ------------------------------------------------------------------
    # 对局动作
    # ------------------------------------------------------------------

    def play_card(
        self, room_id: object, raw_token: str | None, card_id: object, revision: int
    ) -> ServiceResult:
        return self._act(
            room_id,
            raw_token,
            revision,
            lambda state, seat: state.play_card_for(SIDE_BY_SEAT[seat], card_id),
        )

    def use_skill(
        self, room_id: object, raw_token: str | None, revision: int
    ) -> ServiceResult:
        return self._act(
            room_id,
            raw_token,
            revision,
            lambda state, seat: state.use_skill_for(SIDE_BY_SEAT[seat]),
        )

    def end_turn(
        self, room_id: object, raw_token: str | None, revision: int
    ) -> ServiceResult:
        return self._act(
            room_id,
            raw_token,
            revision,
            lambda state, seat: state.end_turn_for(SIDE_BY_SEAT[seat]),
        )

    def respond(
        self, room_id: object, raw_token: str | None, action: str, revision: int
    ) -> ServiceResult:
        return self._act(
            room_id,
            raw_token,
            revision,
            lambda state, seat: state.respond_for(SIDE_BY_SEAT[seat], action),
        )

    def request_rematch(
        self, room_id: object, raw_token: str | None, revision: int
    ) -> ServiceResult:
        auth = self._authorize(room_id, raw_token)
        if not auth.ok:
            return self._from_outcome(auth)
        outcome = self._store.confirm_rematch(auth.room.room_id, auth.seat, revision)
        return self._from_outcome(outcome)

    # ------------------------------------------------------------------
    # 内部：授权与动作
    # ------------------------------------------------------------------

    def _authorize(self, room_id: object, raw_token: str | None) -> RoomOutcome:
        """未带凭证时不做哈希，直接按契约返回未授权，避免空串摘要被当成有效凭证。"""
        if not raw_token:
            return RoomOutcome(
                ok=False,
                code="ROOM_AUTH_REQUIRED",
                message=message_for("ROOM_AUTH_REQUIRED"),
            )
        return self._store.load_authorized_room(room_id, hash_seat_token(raw_token))

    def _act(
        self,
        room_id: object,
        raw_token: str | None,
        revision: int,
        perform: Callable[[BattleState, str], object],
    ) -> ServiceResult:
        auth = self._authorize(room_id, raw_token)
        if not auth.ok:
            return self._from_outcome(auth)
        seat = auth.seat
        outcome = self._store.apply_battle_action(
            auth.room.room_id,
            seat,
            revision,
            lambda state: perform(state, seat),
        )
        return self._from_outcome(outcome)

    def _build_battle(self, player_hero_key: str, enemy_hero_key: str) -> dict:
        """双方锁定后创建一局 PvP；先手与初始能量全由引擎决定，服务不跑 AI。"""
        state = BattleState.create(
            player_hero_key,
            self._rng_factory(),
            mode=PVP_MODE,
            opponent_hero_key=enemy_hero_key,
        )
        return state.to_dict()

    def _from_outcome(self, outcome: RoomOutcome) -> ServiceResult:
        if outcome.ok:
            snapshot = None
            if outcome.room is not None and outcome.seat is not None:
                snapshot = self._snapshot(outcome.room, outcome.seat)
            return ServiceResult(ok=True, snapshot=snapshot)
        return self._failure(outcome.code or "ROOM_STATE_CONFLICT", outcome=outcome)

    def _failure(self, code: str, *, outcome: RoomOutcome | None = None) -> ServiceResult:
        snapshot = None
        if (
            outcome is not None
            and code in SNAPSHOT_ERROR_CODES
            and outcome.room is not None
            and outcome.seat is not None
        ):
            snapshot = self._snapshot(outcome.room, outcome.seat)
        return ServiceResult(ok=False, code=code, message=message_for(code), snapshot=snapshot)

    # ------------------------------------------------------------------
    # 内部：快照拼装
    # ------------------------------------------------------------------

    def _snapshot(self, room: RoomRecord, seat: str) -> dict:
        """把房间元数据与当前座位的公开战场拼成契约里的 RoomSnapshot。"""
        you = room.players[seat]
        opponent = room.players.get(OPPONENT_SEAT[seat])
        finished = room.status == STATUS_FINISHED

        you_state = {
            "nickname": you.nickname,
            "hero_key": you.selected_hero_key,
            "hero_locked": you.selected_hero_key is not None,
            "rematch_confirmed": bool(
                finished and you.rematch_confirmed_for == room.match_number
            ),
        }

        # 对手未加入时整个对象缺失；其余状态只给布尔进度，不泄露英雄。
        opponent_state = None
        if room.status != STATUS_WAITING and opponent is not None:
            opponent_state = {
                "nickname": opponent.nickname,
                "joined": True,
                "hero_locked": opponent.selected_hero_key is not None,
                "rematch_confirmed": bool(
                    finished and opponent.rematch_confirmed_for == room.match_number
                ),
            }

        battle_state = None
        if (
            room.status in (STATUS_PLAYING, STATUS_FINISHED)
            and room.battle_state is not None
        ):
            battle_state = public_battle_state(
                BattleState.from_dict(room.battle_state), SIDE_BY_SEAT[seat]
            )

        return {
            "room": self._room_block(room),
            "you": you_state,
            "opponent": opponent_state,
            "battle": battle_state,
            "rematch": self._rematch_block(room, you, opponent),
        }

    def _room_block(self, room: RoomRecord) -> dict:
        return {
            "room_id": room.room_id,
            "room_code": room.room_code,
            "status": room.status,
            "revision": room.revision,
            "match_number": room.match_number,
            "created_at": room.created_at,
            "updated_at": room.updated_at,
            "expires_at": room.expires_at,
            "invite_url": f"/join?room_code={room.room_code}",
        }

    def _rematch_block(self, room: RoomRecord, you, opponent) -> dict:
        if room.status != STATUS_FINISHED:
            return {"status": REMATCH_NOT_AVAILABLE, "requested_by": None}
        if you.rematch_confirmed_for == room.match_number:
            requested_by = "you"
        elif opponent is not None and opponent.rematch_confirmed_for == room.match_number:
            requested_by = "opponent"
        else:
            requested_by = None
        return {"status": REMATCH_WAITING_CONFIRMATION, "requested_by": requested_by}
