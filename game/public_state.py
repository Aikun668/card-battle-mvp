from game.ai import EnemyIntent, estimate_enemy_intent
from game.battle import ROUND_LIMIT, BattleState
from game.catalog import (
    CARD_TEXTS,
    CARDS,
    EXHAUST_KEYS,
    HERO_DESCRIPTIONS,
    SKILL_COST,
    hero_deck_summary,
)
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


def hero_catalog_entry(hero: HeroDefinition) -> dict:
    """目录接口 /api/heroes 的完整条目：在精简英雄信息上补描述与卡组汇总。

    对局公开状态里的 hero 子对象保持精简——同一份数据不在每个响应里重复膨胀。
    """
    return {
        **_hero_to_dict(hero),
        "description": HERO_DESCRIPTIONS[hero.key],
        "deck": hero_deck_summary(hero.key),
    }


def card_to_dict(card: CardDefinition) -> dict:
    """一张卡牌的公开定义：目录接口、手牌、装备槽、移除区共用同一形状。

    text 是后端生成的效果文案（见 catalog._card_text），前端直接展示，
    不自己拼规则数字。
    """
    return {
        "key": card.key,
        "name": card.name,
        "cost": card.cost,
        "effect_type": card.effect_type,
        "value": card.value,
        "exhaust": card.key in EXHAUST_KEYS,
        "text": CARD_TEXTS[card.key],
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
    return card_to_dict(slot)


def _result_to_dict(battle: BattleState) -> dict | None:
    """终局结果；未结束时是 None（键始终存在，前端可以无条件读）。

    reason 区分四条收尾路径：kill（击倒）/ hp（10 回合结算血多）/
    shield（血量相同、护盾更厚）/ draw（完全平局）。
    """
    if not battle.is_finished():
        return None
    if battle.phase is BattlePhase.DRAW:
        return {
            "winner": None,
            "reason": "draw",
            "text": f"达到 {ROUND_LIMIT} 回合上限，双方生命值与护盾相同，本局平局",
        }
    winner = "player" if battle.phase is BattlePhase.VICTORY else "enemy"
    if battle.player.hp <= 0 or battle.enemy.hp <= 0:
        return {
            "winner": winner,
            "reason": "kill",
            "text": (
                "你击败了对手，本局获胜"
                if winner == "player"
                else "你被电脑击败，本局失败"
            ),
        }
    # 走到这里只可能是 10 回合结算：先比生命值、再比护盾，与结算规则一致。
    if battle.player.hp != battle.enemy.hp:
        reason, subject = "hp", "生命值更高"
    else:
        reason, subject = "shield", "护盾更厚"
    owner = "你" if winner == "player" else "电脑"
    outcome = "本局获胜" if winner == "player" else "本局失败"
    return {
        "winner": winner,
        "reason": reason,
        "text": f"达到 {ROUND_LIMIT} 回合上限，{owner}{subject}，{outcome}",
    }


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
        # 蓄力结余是明牌：下回合开场能多打几张，双方都看得见。
        "bonus_energy_next_turn": participant.bonus_energy_next_turn,
        # 移除区同样是明牌：打出去就没了的东西，对面也算得清。
        "exhaust_pile": list(participant.exhaust_pile),
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
            {"id": card["id"], **card_to_dict(CARDS[card["key"]])}
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
        # 终局结果；未结束时为 None。与 phase 同时给出，结果页直接读。
        "result": _result_to_dict(battle),
        "log": list(battle.log),
    }
