from game.ai import EnemyIntent, estimate_enemy_intent
from game.battle import BattleState
from game.catalog import CARDS, SKILL_COST
from game.models import (
    BattlePhase,
    CardDefinition,
    Combatant,
    HeroDefinition,
    ParticipantState,
    Side,
)


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


def _slot_to_dict(slot: CardDefinition | None) -> dict | None:
    """装备槽里挂着的牌；空槽也要给出 None，两个槽位的键才永远存在。"""
    if slot is None:
        return None
    return _card_to_dict(slot)


def _intent_to_dict(intent: EnemyIntent) -> dict:
    return {
        "kind": intent.kind,
        "source": intent.source,
        "name": intent.name,
        "value": intent.value,
        "text": intent.text,
    }


def _side_to_dict(participant: ParticipantState) -> dict:
    """一方在牌面上公开的全部信息：血条、护盾、能量、英雄、技能状态和装备。

    手牌与抽牌堆不在其中——它们分别由调用方按可见性单独挂上；装备挂在角色身上，
    是谁都看得见的东西，所以它属于这一侧，双方对称输出。
    """
    return {
        **_combatant_to_dict(participant.combatant),
        "hero": _hero_to_dict(participant.hero),
        "skill": {
            "name": participant.hero.skill_name,
            "type": participant.hero.skill_type,
            "value": participant.hero.skill_value,
            "cost": SKILL_COST,
            "used_this_turn": participant.skill_used_this_turn,
        },
        "equipment": {
            "weapon": _slot_to_dict(participant.weapon),
            "armor": _slot_to_dict(participant.armor),
        },
    }


def public_battle_state(battle: BattleState) -> dict:
    is_player_turn = battle.phase is BattlePhase.PLAYER_TURN
    pending_attack = battle.pending_attack
    # 电脑做防御方时响应在结算里当场定夺，不会挂起，所以只有玩家被攻击时才需要页面问响应。
    player_is_defending = (
        pending_attack is not None and pending_attack.defender is Side.PLAYER
    )
    # 双方公开字段完全对称，只有玩家多一份自己的手牌；电脑的手牌与抽牌堆不出现在这里。
    player_state = {
        **_side_to_dict(battle.participant(Side.PLAYER)),
        "hand": [
            {"id": card["id"], **_card_to_dict(CARDS[card["key"]])}
            for card in battle.hand
        ],
    }
    enemy_state = _side_to_dict(battle.participant(Side.ENEMY))
    # 意图只在玩家回合有意义：预告电脑下回合的第一个动作。它是纯查询、确定性的
    # "计划"（不消耗对战随机数，也不改变任何状态），其余时刻一律为 None。
    enemy_state["intent"] = (
        _intent_to_dict(
            estimate_enemy_intent(battle.enemy_observation(), battle.ai_difficulty)
        )
        if is_player_turn
        else None
    )
    return {
        "phase": battle.phase.value,
        "round_number": battle.round_number,
        "starting_side": battle.starting_side.value,
        "ai_difficulty": battle.ai_difficulty.value,
        "player": player_state,
        "enemy": enemy_state,
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
                and battle.player.energy >= SKILL_COST
            ),
            "end_turn": is_player_turn and not battle.is_finished(),
            "respond": {
                "dodge": battle.can_dodge(),
                "pass": player_is_defending,
            },
        },
        "log": list(battle.log),
    }
