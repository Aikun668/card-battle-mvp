import random
from dataclasses import dataclass, replace
from typing import Literal

from game.catalog import CARDS, STARTING_ENERGY
from game.models import AIDifficulty, CardDefinition

# 电脑没有英雄技能，也无法主动打出只能在响应时机使用的牌。
ENEMY_UNUSABLE_EFFECTS = frozenset({"dodge"})

LETHAL_BONUS = 1000.0
EFFICIENCY_WEIGHT = 0.5
PASS_SCORE = 0.5
# 削掉护盾是通往击杀的进度，但本身不扣血，所以单价明显低于真实伤害；
# 若记 0 分，电脑面对高护盾玩家会永远选择空过，直接放弃获胜。
SHIELD_BREAK_WEIGHT = 0.4
SHIELD_SCALE = 12.0
# 平方增长：失血越多，治疗与护盾的边际价值上升越快，濒死时自然转向自保。
RISK_WEIGHT = 6.0
# 困难模式发现玩家下回合能击杀自己时，对非防御行动的扣分。
DANGER_PENALTY = 100.0

DEFENSIVE_EFFECTS = frozenset({"shield", "heal"})

DIFFICULTY_SELECTION: dict[AIDifficulty, tuple[float, ...]] = {
    AIDifficulty.EASY: (0.60, 0.25, 0.15),
    AIDifficulty.MEDIUM: (0.88, 0.12),
}


@dataclass(frozen=True)
class ActionCandidate:
    kind: Literal["card", "pass"]
    card_id: str | None = None
    card_key: str | None = None
    score: float = 0.0


def get_available_enemy_actions(state) -> list[ActionCandidate]:
    candidates = [
        ActionCandidate(kind="card", card_id=card["id"], card_key=card["key"])
        for card in state.enemy_hand
        if CARDS[card["key"]].effect_type not in ENEMY_UNUSABLE_EFFECTS
        and CARDS[card["key"]].cost <= state.enemy.energy
    ]
    candidates.append(ActionCandidate(kind="pass"))
    return candidates


def _risk_multiplier(combatant) -> float:
    missing_ratio = 1 - combatant.hp / combatant.max_hp
    return 1 + missing_ratio**2 * RISK_WEIGHT


def score_damage(state, definition: CardDefinition) -> float:
    # 超出剩余生命的部分完全浪费；打在护盾上的部分只算削盾价值，不算生命威胁。
    absorbed = min(definition.value, state.player.shield)
    effective = definition.value - absorbed
    useful = min(effective, state.player.hp)
    score = useful + useful / definition.cost * EFFICIENCY_WEIGHT
    score += absorbed * SHIELD_BREAK_WEIGHT
    if effective >= state.player.hp:
        score += LETHAL_BONUS
    return score


def score_heal(state, definition: CardDefinition) -> float:
    restored = min(definition.value, state.enemy.max_hp - state.enemy.hp)
    return restored * _risk_multiplier(state.enemy)


def score_shield(state, definition: CardDefinition) -> float:
    # 已有护盾越多，继续叠盾的边际收益越低。
    diminishing = 1 + state.enemy.shield / SHIELD_SCALE
    return definition.value / diminishing * _risk_multiplier(state.enemy)


def score_pass() -> float:
    # 高于任何零收益动作，低于任何有正收益的动作。
    return PASS_SCORE


def _base_score(state, candidate: ActionCandidate) -> float:
    if candidate.kind == "pass":
        return score_pass()
    definition = CARDS[candidate.card_key]
    if definition.effect_type == "damage":
        return score_damage(state, definition)
    if definition.effect_type == "heal":
        return score_heal(state, definition)
    if definition.effect_type == "shield":
        return score_shield(state, definition)
    return 0.0


def estimate_player_threat(state) -> int:
    """玩家下回合能量允许打出的最高单张伤害。"""
    values = [
        CARDS[card["key"]].value
        for card in state.hand
        if CARDS[card["key"]].effect_type == "damage"
        and CARDS[card["key"]].cost <= STARTING_ENERGY
    ]
    return max(values, default=0)


def _survivable_hp_after(state, candidate: ActionCandidate) -> int:
    hp = state.enemy.hp
    shield = state.enemy.shield
    if candidate.kind == "card":
        definition = CARDS[candidate.card_key]
        if definition.effect_type == "shield":
            shield += definition.value
        elif definition.effect_type == "heal":
            hp = min(state.enemy.max_hp, hp + definition.value)
    return hp + shield


def hard_lookahead_adjustment(state, candidate: ActionCandidate) -> float:
    """只做一步估算：玩家下回合是否可能击杀自己。不执行动作、不递归模拟。"""
    threat = estimate_player_threat(state)
    if threat <= 0:
        return 0.0
    if _survivable_hp_after(state, candidate) > threat:
        return 0.0
    if (
        candidate.kind == "card"
        and CARDS[candidate.card_key].effect_type in DEFENSIVE_EFFECTS
    ):
        return 0.0
    return -DANGER_PENALTY


def score_enemy_action(
    state, candidate: ActionCandidate, difficulty: AIDifficulty
) -> float:
    score = _base_score(state, candidate)
    if difficulty is AIDifficulty.HARD:
        score += hard_lookahead_adjustment(state, candidate)
    return score


def rank_enemy_actions(state, difficulty: AIDifficulty) -> list[ActionCandidate]:
    scored = [
        replace(candidate, score=score_enemy_action(state, candidate, difficulty))
        for candidate in get_available_enemy_actions(state)
    ]
    return sorted(scored, key=lambda candidate: candidate.score, reverse=True)


def select_enemy_action(
    state, difficulty: AIDifficulty, rng: random.Random
) -> ActionCandidate:
    ranked = rank_enemy_actions(state, difficulty)
    weights = DIFFICULTY_SELECTION.get(difficulty)
    if weights is None:
        return ranked[0]
    # 比空过更强的动作才参与抽取：简单难度可以选得差，但不该浪费整回合不做任何事。
    usable = [candidate for candidate in ranked if candidate.score > PASS_SCORE]
    if not usable:
        return ranked[0]
    pool = usable[: len(weights)]
    return rng.choices(pool, weights=weights[: len(pool)], k=1)[0]
