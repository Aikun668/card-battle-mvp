from game.ai import EnemyIntent, estimate_enemy_intent
from game.battle import PVE_MODE, PVP_MODE, ROUND_LIMIT, BattleState
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

    文案随模式走：人机模式可以对玩家说"你 / 电脑"；双人热座的回应是共享的，
    必须中性（"玩家1 / 玩家2"），否则对其中一方总是错的。
    """
    if not battle.is_finished():
        return None
    pvp = battle.mode == PVP_MODE
    if battle.phase is BattlePhase.DRAW:
        return {
            "winner": None,
            "reason": "draw",
            "text": f"达到 {ROUND_LIMIT} 回合上限，双方生命值与护盾相同，本局平局",
        }
    winner = "player" if battle.phase is BattlePhase.VICTORY else "enemy"
    if battle.player.hp <= 0 or battle.enemy.hp <= 0:
        if pvp:
            text = f"{battle.side_label(Side(winner))}击败对手，本局获胜"
        elif winner == "player":
            text = "你击败了对手，本局获胜"
        else:
            text = "你被电脑击败，本局失败"
        return {"winner": winner, "reason": "kill", "text": text}
    # 走到这里只可能是 10 回合结算：先比生命值、再比护盾，与结算规则一致。
    if battle.player.hp != battle.enemy.hp:
        reason, subject = "hp", "生命值更高"
    else:
        reason, subject = "shield", "护盾更厚"
    if pvp:
        text = (
            f"达到 {ROUND_LIMIT} 回合上限，"
            f"{battle.side_label(Side(winner))}{subject}，本局获胜"
        )
    else:
        owner = "你" if winner == "player" else "电脑"
        outcome = "本局获胜" if winner == "player" else "本局失败"
        text = f"达到 {ROUND_LIMIT} 回合上限，{owner}{subject}，{outcome}"
    return {"winner": winner, "reason": reason, "text": text}


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


def public_battle_state(battle: BattleState, viewer: Side = Side.PLAYER) -> dict:
    """一份"给某个座位看"的公开状态。

    viewer 决定三件事：手牌只挂在自己一侧、available_actions 只回答自己的操作、
    response.active 只描述自己是否需要响应。其余公开信息（血、盾、能量、装备、
    移除区、意图）双方完全对称。

    人机模式下调用方永远用默认的 viewer=player，输出与旧契约完全一致；
    双人热座按当前操作者传 viewer，谁的手牌就挂在谁那一侧。
    """
    is_viewer_turn = battle.current_side() is viewer
    pending_attack = battle.pending_attack
    # 挂起的攻击只会等真人防守方（电脑防守在结算里当场定夺、不会挂起），
    # 所以"该响应的人"就是 viewer 当且仅当 viewer 是这次攻击的防守方。
    viewer_is_defending = (
        pending_attack is not None and pending_attack.defender is viewer
    )
    viewer_participant = battle.participant(viewer)
    # 双方公开字段完全对称；手牌是私有信息，只挂在 viewer 自己那一侧。
    player_state = _side_to_dict(battle.participant(Side.PLAYER))
    enemy_state = _side_to_dict(battle.participant(Side.ENEMY))
    viewer_state = player_state if viewer is Side.PLAYER else enemy_state
    viewer_state["hand"] = [
        {"id": card["id"], **card_to_dict(CARDS[card["key"]])}
        for card in viewer_participant.hand
    ]
    # 意图只在"人机模式的玩家回合"有意义：预告电脑下回合的第一个动作。它是纯查询、
    # 确定性的"计划"（不消耗对战随机数，也不改变任何状态），其余时刻一律为 None。
    # 双人热座没有电脑计划，恒为 None。
    enemy_state["intent"] = (
        _intent_to_dict(
            estimate_enemy_intent(battle.enemy_observation(), battle.ai_difficulty)
        )
        if battle.mode == PVE_MODE and battle.phase is BattlePhase.PLAYER_TURN
        else None
    )
    return {
        "phase": battle.phase.value,
        "mode": battle.mode,
        "viewer": viewer.value,
        "round_number": battle.round_number,
        "starting_side": battle.starting_side.value,
        "ai_difficulty": battle.ai_difficulty.value,
        "player": player_state,
        "enemy": enemy_state,
        "response": {
            # active 是"该我响应吗"。攻击方视角下依然能读到 attacker / 牌名 / 伤害
            # （挂起本身是公开信息），只是 active 为 false。
            "active": viewer_is_defending,
            "attacker": pending_attack.attacker.value if pending_attack else None,
            "card_name": pending_attack.card_name if pending_attack else None,
            "damage": pending_attack.damage if pending_attack else 0,
            "dodge_cost": CARDS["dodge"].cost,
        },
        "available_actions": {
            "play_card": is_viewer_turn and not battle.is_finished(),
            "use_skill": (
                is_viewer_turn
                and not battle.is_finished()
                and not viewer_participant.skill_used_this_turn
                and viewer_participant.combatant.energy >= SKILL_COST
            ),
            "end_turn": is_viewer_turn and not battle.is_finished(),
            "respond": {
                "dodge": battle.can_respond_dodge(viewer),
                "pass": viewer_is_defending,
            },
        },
        # 终局结果；未结束时为 None。与 phase 同时给出，结果页直接读。
        "result": _result_to_dict(battle),
        "log": list(battle.log),
    }
