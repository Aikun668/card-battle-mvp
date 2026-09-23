import random

from flask import Blueprint, jsonify, request, session

from game.battle import PVE_MODE, PVP_MODE, BattleState
from game.catalog import CARDS, HEROES
from game.models import AIDifficulty, BattlePhase, Side
from game.public_state import (
    card_to_dict,
    hero_catalog_entry,
    public_battle_state,
)
from game.session_state import clear_battle, load_battle
from web_support import RESULT_SAVED_KEY, persist_battle


def create_api_blueprint() -> Blueprint:
    api = Blueprint("api", __name__, url_prefix="/api")

    def response(data=None, *, status=200, error=None):
        return jsonify({"ok": error is None, "data": data, "error": error}), status

    def error_response(code: str, message: str, *, status: int, data=None):
        return response(
            data,
            status=status,
            error={"code": code, "message": message},
        )

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
        # opponent_hero_key 只在双人模式生效（玩家2 选的英雄）；人机模式忽略。
        opponent_hero_key = payload.get("opponent_hero_key")
        if (
            mode == PVP_MODE
            and opponent_hero_key is not None
            and opponent_hero_key not in HEROES
        ):
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
        if action not in {"dodge", "pass"}:
            return error_response(
                "INVALID_REQUEST",
                "响应操作必须是 dodge 或 pass",
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

    return api
