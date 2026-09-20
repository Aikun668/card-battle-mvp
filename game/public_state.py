from game.battle import BattleState
from game.catalog import CARDS
from game.models import BattlePhase, CardDefinition, Combatant, HeroDefinition, Side


def _hero_to_dict(hero: HeroDefinition) -> dict:
    return {
        "key": hero.key,
        "name": hero.name,
        "max_hp": hero.max_hp,
        "skill_name": hero.skill_name,
        "skill_type": hero.skill_type,
        "skill_value": hero.skill_value,
    }


def _card_to_dict(card: CardDefinition) -> dict:
    return {
        "key": card.key,
        "name": card.name,
        "cost": card.cost,
        "effect_type": card.effect_type,
        "value": card.value,
    }


def _combatant_to_dict(combatant: Combatant) -> dict:
    return {
        "name": combatant.name,
        "max_hp": combatant.max_hp,
        "hp": combatant.hp,
        "shield": combatant.shield,
        "energy": combatant.energy,
    }


def public_battle_state(battle: BattleState) -> dict:
    is_player_turn = battle.phase is BattlePhase.PLAYER_TURN
    pending_attack = battle.pending_attack
    # 电脑做防御方时响应在结算里当场定夺，不会挂起，所以只有玩家被攻击时才需要页面问响应。
    player_is_defending = (
        pending_attack is not None and pending_attack.defender is Side.PLAYER
    )
    return {
        "phase": battle.phase.value,
        "round_number": battle.round_number,
        "ai_difficulty": battle.ai_difficulty.value,
        "hero": _hero_to_dict(battle.hero),
        "player": _combatant_to_dict(battle.player),
        "enemy": _combatant_to_dict(battle.enemy),
        "hand": [
            {"id": card["id"], **_card_to_dict(CARDS[card["key"]])}
            for card in battle.hand
        ],
        "skill": {
            "name": battle.hero.skill_name,
            "type": battle.hero.skill_type,
            "value": battle.hero.skill_value,
            "cost": 2,
            "used_this_turn": battle.skill_used_this_turn,
        },
        "response": {
            "active": player_is_defending,
            "card_name": pending_attack.card_name if player_is_defending else None,
            "damage": pending_attack.damage if player_is_defending else 0,
            "dodge_cost": CARDS["dodge"].cost,
        },
        "available_actions": {
            "play_card": is_player_turn and not battle.is_finished(),
            "use_skill": (
                is_player_turn
                and not battle.is_finished()
                and not battle.skill_used_this_turn
                and battle.player.energy >= 2
            ),
            "end_turn": is_player_turn and not battle.is_finished(),
            "respond": {
                "dodge": battle.can_dodge(),
                "pass": player_is_defending,
            },
        },
        "log": list(battle.log),
    }
