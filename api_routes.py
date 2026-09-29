import random

from flask import Blueprint, jsonify, request, session

from game.battle import PVE_MODE, PVP_MODE, BattleState
from game.catalog import CARDS, HEROES
from game.models import AIDifficulty, BattlePhase, Side
from game.online_battle_service import OnlineBattleService, hash_seat_token
from game.public_state import (
    card_to_dict,
    hero_catalog_entry,
    public_battle_state,
)
from game.session_state import clear_battle, load_battle
from web_support import RESULT_SAVED_KEY, persist_battle

# 座位凭证原文只存在这个 Session 键里，按 room_id 分桶；它随签名 Cookie 往返，
# 前端 JavaScript 既不读取也不拼接。数据库只保存它的 sha256 摘要。
TOKEN_SESSION_KEY = "online_tokens"

_RESPOND_ACTIONS = frozenset({"dodge", "negate", "pass"})

# 契约 §6.1 的错误码 → HTTP 状态；服务层只给机器码，由路由决定状态码与是否带快照。
ROOM_ERROR_STATUS = {
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


def _is_revision(value: object) -> bool:
    """revision 必须是真正的非负整数；布尔是 int 的子类，但语义上不是版本号。"""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def create_api_blueprint(online_service: OnlineBattleService | None = None) -> Blueprint:
    api = Blueprint("api", __name__, url_prefix="/api")

    def response(data=None, *, status=200, error=None):
        return jsonify({"ok": error is None, "data": data, "error": error}), status

    def error_response(code: str, message: str, *, status: int, data=None):
        return response(
            data,
            status=status,
            error={"code": code, "message": message},
        )

    @api.after_request
    def disable_caching(response_object):
        # 任何响应都可能带私有手牌或房间快照，禁止浏览器与代理缓存（契约 §2.1）。
        response_object.headers["Cache-Control"] = "no-store"
        return response_object

    def current_battle():
        battle = load_battle(session)
        if battle is None:
            return None, error_response(
                "NO_ACTIVE_GAME", "当前没有进行中的对局", status=404
            )
        return battle, None

    def resolve_seat(raw: object, battle: BattleState):
        """把请求里的 seat 参数解析成一个"由真人操作"的座位。

        省略时默认 player——人机模式的旧调用（不带 seat）行为零变化。
        值非法、或该座位由电脑操作（人机模式的 enemy）时返回 INVALID_SEAT：
        这是结构性错误，不是战斗规则拒绝，所以用 400 而不是 422。
        """
        if raw is None:
            seat = Side.PLAYER
        elif raw in {side.value for side in Side}:
            seat = Side(raw)
        else:
            return None, error_response(
                "INVALID_SEAT", "座位必须是 player 或 enemy", status=400
            )
        if not battle.is_human_side(seat):
            return None, error_response(
                "INVALID_SEAT", "这个座位由电脑操作，不能由请求方代替行动", status=400
            )
        return seat, None

    @api.get("/heroes")
    def heroes_catalog():
        return response([hero_catalog_entry(hero) for hero in HEROES.values()])

    @api.get("/cards")
    def cards_catalog():
        return response([card_to_dict(card) for card in CARDS.values()])

    @api.get("/game")
    def get_game():
        battle, error = current_battle()
        if error:
            return error
        # 视角用 query 参数选（GET 没有请求体）：?seat=enemy 取玩家2 的视角。
        seat, seat_error = resolve_seat(request.args.get("seat"), battle)
        if seat_error:
            return seat_error
        return response(public_battle_state(battle, viewer=seat))

    @api.post("/game")
    def create_game():
        payload = request.get_json(silent=True) or {}
        hero_key = payload.get("hero_key")
        if hero_key not in HEROES:
            return error_response("INVALID_HERO", "请选择有效角色", status=422)
        difficulty_value = payload.get("ai_difficulty", AIDifficulty.MEDIUM.value)
        ai_difficulty = AIDifficulty.parse(difficulty_value)
        if ai_difficulty is None:
            return error_response(
                "INVALID_DIFFICULTY", "请选择有效的电脑难度", status=422
            )
        mode = payload.get("mode", PVE_MODE)
        if mode not in {PVE_MODE, PVP_MODE}:
            return error_response("INVALID_MODE", "模式必须是 pve 或 pvp", status=422)
        # opponent_hero_key 指定对位英雄：双人模式下是玩家2 选的英雄，人机模式下
        # 可用来指定电脑英雄（省略则随机抽取）。两种模式都校验非法值——曾经只在
        # pvp 下校验，pve 传非法值时会在模型层 KeyError 变成 500。
        opponent_hero_key = payload.get("opponent_hero_key")
        if opponent_hero_key is not None and opponent_hero_key not in HEROES:
            return error_response("INVALID_HERO", "请选择有效角色", status=422)
        # 电脑先手时 create() 已经同步跑完它开局的整个回合（人机模式），这里只会拿到
        # 玩家回合、响应窗口或终局；双人模式下没有电脑席位，先手是玩家2 时直接返回 ENEMY_TURN。
        battle = BattleState.create(
            hero_key,
            random.Random(),
            ai_difficulty,
            mode=mode,
            opponent_hero_key=opponent_hero_key,
        )
        session.pop(RESULT_SAVED_KEY, None)
        persist_battle(session, battle)
        return response(public_battle_state(battle), status=201)

    @api.post("/game/actions/card")
    def play_card():
        battle, error = current_battle()
        if error:
            return error
        payload = request.get_json(silent=True) or {}
        card_id = payload.get("card_id")
        if not isinstance(card_id, str) or not card_id:
            return error_response("INVALID_REQUEST", "需要提供 card_id", status=400)
        seat, seat_error = resolve_seat(payload.get("seat"), battle)
        if seat_error:
            return seat_error
        result = battle.play_card_for(seat, card_id)
        persist_battle(session, battle)
        if not result.ok:
            return error_response(
                "ACTION_REJECTED",
                result.message,
                status=422,
                data=public_battle_state(battle, viewer=seat),
            )
        return response(public_battle_state(battle, viewer=seat))

    @api.post("/game/actions/skill")
    def use_skill():
        battle, error = current_battle()
        if error:
            return error
        payload = request.get_json(silent=True) or {}
        seat, seat_error = resolve_seat(payload.get("seat"), battle)
        if seat_error:
            return seat_error
        result = battle.use_skill_for(seat)
        persist_battle(session, battle)
        if not result.ok:
            return error_response(
                "ACTION_REJECTED",
                result.message,
                status=422,
                data=public_battle_state(battle, viewer=seat),
            )
        return response(public_battle_state(battle, viewer=seat))

    @api.post("/game/actions/end-turn")
    def end_turn():
        battle, error = current_battle()
        if error:
            return error
        payload = request.get_json(silent=True) or {}
        seat, seat_error = resolve_seat(payload.get("seat"), battle)
        if seat_error:
            return seat_error
        result = battle.end_turn_for(seat)
        if not result.ok:
            persist_battle(session, battle)
            return error_response(
                "ACTION_REJECTED",
                result.message,
                status=422,
                data=public_battle_state(battle, viewer=seat),
            )
        # 打满回合上限时结束回合就直接收尾判出胜负，没有电脑回合可跑。
        # 只有电脑控制的座位才在这里把回合跑完；双人热座下 ENEMY_TURN 是
        # "等玩家2 操作"，原样交给调用方。
        if battle.phase is BattlePhase.ENEMY_TURN and not battle.is_human_side(
            Side.ENEMY
        ):
            battle.resolve_enemy_turn()
        persist_battle(session, battle)
        return response(public_battle_state(battle, viewer=seat))

    @api.post("/game/actions/respond")
    def respond():
        battle, error = current_battle()
        if error:
            return error
        payload = request.get_json(silent=True) or {}
        action = payload.get("action")
        if action not in {"dodge", "negate", "pass"}:
            return error_response(
                "INVALID_REQUEST",
                "响应操作必须是 dodge、negate 或 pass",
                status=400,
            )
        seat, seat_error = resolve_seat(payload.get("seat"), battle)
        if seat_error:
            return seat_error
        result = battle.respond_for(seat, action)
        persist_battle(session, battle)
        if not result.ok:
            return error_response(
                "ACTION_REJECTED",
                result.message,
                status=422,
                data=public_battle_state(battle, viewer=seat),
            )
        return response(public_battle_state(battle, viewer=seat))

    @api.post("/game/restart")
    def restart_game():
        clear_battle(session)
        session.pop(RESULT_SAVED_KEY, None)
        return response(None)

    # ------------------------------------------------------------------
    # 在线 PvP（接口契约 v1）
    # ------------------------------------------------------------------

    def stored_tokens() -> dict:
        tokens = session.get(TOKEN_SESSION_KEY)
        return tokens if isinstance(tokens, dict) else {}

    def stored_raw_token(room_id: object) -> str | None:
        """按 room_id 取本浏览器的座位凭证原文；没有则返回 None 走未授权分支。"""
        if not isinstance(room_id, str):
            return None
        token = stored_tokens().get(room_id)
        return token if isinstance(token, str) else None

    def remember_token(room_id: object, raw_token: str | None) -> None:
        if not isinstance(room_id, str) or not raw_token:
            return
        tokens = dict(stored_tokens())
        tokens[room_id] = raw_token
        session[TOKEN_SESSION_KEY] = tokens

    def known_token_hashes() -> list[str]:
        """本浏览器已持有的全部凭证摘要，用于拒绝自己加入自己的房间。"""
        return [hash_seat_token(token) for token in stored_tokens().values() if token]

    def require_service():
        if online_service is None:
            return error_response("ROOM_NOT_FOUND", "在线房间功能未启用", status=404)
        return None

    def room_payload(required: set[str]):
        """严格校验请求体：必须是 JSON 对象，且字段集合与契约完全一致。"""
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return None, error_response(
                "INVALID_REQUEST", "请求体必须是 JSON 对象", status=400
            )
        if set(payload) - required:
            return None, error_response(
                "INVALID_REQUEST", "请求体包含未定义字段", status=400
            )
        if required - set(payload):
            return None, error_response(
                "INVALID_REQUEST", "请求体缺少必填字段", status=400
            )
        return payload, None

    def revision_error():
        return error_response("INVALID_REQUEST", "revision 必须是非负整数", status=400)

    def service_failure(result):
        code = result.code or "ROOM_STATE_CONFLICT"
        return error_response(
            code,
            result.message or code,
            status=ROOM_ERROR_STATUS.get(code, 409),
            data=result.snapshot,
        )

    def revision_action(room_id: str, method_name: str):
        """带 revision 的统一读写路径：鉴权、版本比较、状态检查都在服务层。"""
        guard = require_service()
        if guard:
            return guard
        payload, error = room_payload({"revision"})
        if error:
            return error
        if not _is_revision(payload["revision"]):
            return revision_error()
        result = getattr(online_service, method_name)(
            room_id, stored_raw_token(room_id), payload["revision"]
        )
        if not result.ok:
            return service_failure(result)
        return response(result.snapshot)

    @api.post("/rooms")
    def online_create_room():
        guard = require_service()
        if guard:
            return guard
        payload, error = room_payload({"nickname"})
        if error:
            return error
        result = online_service.create_room(payload["nickname"])
        if not result.ok:
            return service_failure(result)
        room = (result.snapshot or {}).get("room") or {}
        remember_token(room.get("room_id"), result.raw_token)
        return response(result.snapshot, status=201)

    @api.post("/rooms/join")
    def online_join_room():
        guard = require_service()
        if guard:
            return guard
        payload, error = room_payload({"room_code", "nickname"})
        if error:
            return error
        result = online_service.join_room(
            payload["room_code"],
            payload["nickname"],
            known_token_hashes=known_token_hashes(),
        )
        if not result.ok:
            return service_failure(result)
        room = (result.snapshot or {}).get("room") or {}
        remember_token(room.get("room_id"), result.raw_token)
        return response(result.snapshot)

    @api.get("/rooms/<room_id>")
    def online_get_room(room_id: str):
        guard = require_service()
        if guard:
            return guard
        result = online_service.get_room_state(room_id, stored_raw_token(room_id))
        if not result.ok:
            return service_failure(result)
        return response(result.snapshot)

    @api.post("/rooms/<room_id>/hero")
    def online_lock_hero(room_id: str):
        guard = require_service()
        if guard:
            return guard
        payload, error = room_payload({"hero_key", "revision"})
        if error:
            return error
        if not _is_revision(payload["revision"]):
            return revision_error()
        result = online_service.lock_hero(
            room_id,
            stored_raw_token(room_id),
            payload["hero_key"],
            payload["revision"],
        )
        if not result.ok:
            return service_failure(result)
        return response(result.snapshot)

    @api.post("/rooms/<room_id>/actions/card")
    def online_play_card(room_id: str):
        guard = require_service()
        if guard:
            return guard
        payload, error = room_payload({"card_id", "revision"})
        if error:
            return error
        if not _is_revision(payload["revision"]):
            return revision_error()
        result = online_service.play_card(
            room_id,
            stored_raw_token(room_id),
            payload["card_id"],
            payload["revision"],
        )
        if not result.ok:
            return service_failure(result)
        return response(result.snapshot)

    @api.post("/rooms/<room_id>/actions/skill")
    def online_use_skill(room_id: str):
        return revision_action(room_id, "use_skill")

    @api.post("/rooms/<room_id>/actions/end-turn")
    def online_end_turn(room_id: str):
        return revision_action(room_id, "end_turn")

    @api.post("/rooms/<room_id>/actions/respond")
    def online_respond(room_id: str):
        guard = require_service()
        if guard:
            return guard
        payload, error = room_payload({"action", "revision"})
        if error:
            return error
        if payload["action"] not in _RESPOND_ACTIONS:
            return error_response(
                "INVALID_REQUEST", "响应操作必须是 dodge、negate 或 pass", status=400
            )
        if not _is_revision(payload["revision"]):
            return revision_error()
        result = online_service.respond(
            room_id,
            stored_raw_token(room_id),
            payload["action"],
            payload["revision"],
        )
        if not result.ok:
            return service_failure(result)
        return response(result.snapshot)

    @api.post("/rooms/<room_id>/rematch")
    def online_rematch(room_id: str):
        return revision_action(room_id, "request_rematch")

    return api
