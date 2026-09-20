import random

from flask import Blueprint, jsonify, request, session

from game.battle import BattleState
from game.catalog import CARDS, HEROES
from game.models import AIDifficulty, BattlePhase
from game.public_state import public_battle_state
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

    @api.get("/heroes")
    def heroes_catalog():
        return response(
            [
                {
                    "key": hero.key,
                    "name": hero.name,
                    "max_hp": hero.max_hp,
                    "skill_name": hero.skill_name,
                    "skill_type": hero.skill_type,
                    "skill_value": hero.skill_value,
                }
                for hero in HEROES.values()
            ]
        )

    @api.get("/cards")
    def cards_catalog():
        return response(
            [
                {
                    "key": card.key,
                    "name": card.name,
                    "cost": card.cost,
                    "effect_type": card.effect_type,
                    "value": card.value,
                }
                for card in CARDS.values()
            ]
        )

    @api.get("/game")
    def get_game():
        battle, error = current_battle()
        if error:
            return error
        return response(public_battle_state(battle))

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
        # 电脑先手时 create() 已经同步跑完它开局的整个回合，这里只会拿到玩家回合或终局。
        battle = BattleState.create(hero_key, random.Random(), ai_difficulty)
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
        result = battle.play_card(card_id)
        persist_battle(session, battle)
        if not result.ok:
            return error_response(
                "ACTION_REJECTED",
                result.message,
                status=422,
                data=public_battle_state(battle),
            )
        return response(public_battle_state(battle))

    @api.post("/game/actions/skill")
    def use_skill():
        battle, error = current_battle()
        if error:
            return error
        result = battle.use_skill()
        persist_battle(session, battle)
        if not result.ok:
            return error_response(
                "ACTION_REJECTED",
                result.message,
                status=422,
                data=public_battle_state(battle),
            )
        return response(public_battle_state(battle))

    @api.post("/game/actions/end-turn")
    def end_turn():
        battle, error = current_battle()
        if error:
            return error
        result = battle.end_player_turn()
        if not result.ok:
            persist_battle(session, battle)
            return error_response(
                "ACTION_REJECTED",
                result.message,
                status=422,
                data=public_battle_state(battle),
            )
        # 打满回合上限时玩家结束回合就直接判平局，没有电脑回合可跑。
        if battle.phase is BattlePhase.ENEMY_TURN:
            battle.resolve_enemy_turn()
        persist_battle(session, battle)
        return response(public_battle_state(battle))

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
        result = battle.respond(action)
        persist_battle(session, battle)
        if not result.ok:
            return error_response(
                "ACTION_REJECTED",
                result.message,
                status=422,
                data=public_battle_state(battle),
            )
        return response(public_battle_state(battle))

    @api.post("/game/restart")
    def restart_game():
        clear_battle(session)
        session.pop(RESULT_SAVED_KEY, None)
        return response(None)

    return api
