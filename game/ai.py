import random
from dataclasses import dataclass, replace
from typing import Literal

from game.catalog import CARDS, SKILL_COST, STARTING_ENERGY
from game.models import AIDifficulty, CardDefinition, HeroDefinition, Side

# 闪避只能在响应时机使用，不进入主动出牌候选。
ENEMY_UNUSABLE_EFFECTS = frozenset({"dodge"})

LETHAL_BONUS = 1000.0
EFFICIENCY_WEIGHT = 0.5
PASS_SCORE = 0.5
# 手里留着闪避时，最后 1 点能量的价值高于任何低收益动作。
DODGE_HOLD_BONUS = 3.0
# 削掉护盾是通往击杀的进度，但本身不扣血，所以单价明显低于真实伤害；
# 若记 0 分，电脑面对高护盾玩家会永远选择空过，直接放弃获胜。
SHIELD_BREAK_WEIGHT = 0.4
SHIELD_SCALE = 12.0
# 平方增长：失血越多，治疗与护盾的边际价值上升越快，濒死时自然转向自保。
RISK_WEIGHT = 6.0
# 困难模式发现玩家下回合能击杀自己时，对非防御行动的扣分。
DANGER_PENALTY = 100.0

DEFENSIVE_EFFECTS = frozenset({"shield", "heal"})

# 技能按等效卡牌参与评分：护盾类算护盾牌，其余（含伤害加抽牌）算伤害牌。
SKILL_EFFECT_TYPES = {"shield": "shield", "damage": "damage", "damage_draw": "damage"}

DIFFICULTY_SELECTION: dict[AIDifficulty, tuple[float, ...]] = {
    AIDifficulty.EASY: (0.60, 0.25, 0.15),
    AIDifficulty.MEDIUM: (0.88, 0.12),
}


@dataclass(frozen=True)
class ActionCandidate:
    kind: Literal["card", "skill", "dodge", "pass"]
    card_id: str | None = None
    card_key: str | None = None
    score: float = 0.0


def get_available_enemy_actions(state) -> list[ActionCandidate]:
    participant = state.participant(Side.ENEMY)
    candidates = [
        ActionCandidate(kind="card", card_id=card["id"], card_key=card["key"])
        for card in participant.hand
        if CARDS[card["key"]].effect_type not in ENEMY_UNUSABLE_EFFECTS
        and CARDS[card["key"]].cost <= participant.combatant.energy
    ]
    if (
        not participant.skill_used_this_turn
        and participant.combatant.energy >= SKILL_COST
    ):
        candidates.append(ActionCandidate(kind="skill"))
    candidates.append(ActionCandidate(kind="pass"))
    return candidates


def _skill_as_card(hero: HeroDefinition) -> CardDefinition:
    return CardDefinition(
        key=hero.key,
        name=hero.skill_name,
        cost=SKILL_COST,
        effect_type=SKILL_EFFECT_TYPES[hero.skill_type],
        value=hero.skill_value,
    )


def _definition_of(state, candidate: ActionCandidate) -> CardDefinition | None:
    if candidate.kind == "card":
        return CARDS[candidate.card_key]
    if candidate.kind == "skill":
        return _skill_as_card(state.participant(Side.ENEMY).hero)
    return None


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


def _holds_the_last_dodge_energy(state) -> bool:
    """手里有闪避、能量又只够再打一张牌：再花掉就没法闪避了。"""
    if state.enemy.energy > CARDS["dodge"].cost:
        return False
    return any(card["key"] == "dodge" for card in state.enemy_hand)


def score_pass(state, difficulty: AIDifficulty) -> float:
    # 高于任何零收益动作，低于任何有正收益的动作。
    if difficulty is AIDifficulty.EASY:
        return PASS_SCORE
    if _holds_the_last_dodge_energy(state):
        return PASS_SCORE + DODGE_HOLD_BONUS
    return PASS_SCORE


def _base_score(state, candidate: ActionCandidate, difficulty: AIDifficulty) -> float:
    if candidate.kind == "pass":
        return score_pass(state, difficulty)
    definition = _definition_of(state, candidate)
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
    definition = _definition_of(state, candidate)
    if definition is not None:
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
    definition = _definition_of(state, candidate)
    if definition is not None and definition.effect_type in DEFENSIVE_EFFECTS:
        return 0.0
    return -DANGER_PENALTY


def score_enemy_action(
    state, candidate: ActionCandidate, difficulty: AIDifficulty
) -> float:
    score = _base_score(state, candidate, difficulty)
    if difficulty is AIDifficulty.HARD:
        score += hard_lookahead_adjustment(state, candidate)
    return score


def score_dodge(state) -> float:
    """电脑闪避这次攻击值多少分：救下护盾吸收之后真会掉的生命。"""
    pending = state.pending_attack
    absorbed = min(state.enemy.shield, pending.damage)
    saved = min(pending.damage - absorbed, state.enemy.hp)
    if saved <= 0:
        return 0.0
    return saved * _risk_multiplier(state.enemy)


def rank_enemy_responses(state, difficulty: AIDifficulty) -> list[ActionCandidate]:
    """响应窗口里电脑只有两个合法动作；分数与出牌共用同一套评分口径。"""
    candidates = [
        ActionCandidate(kind="dodge", score=score_dodge(state)),
        ActionCandidate(kind="pass", score=score_pass(state, difficulty)),
    ]
    return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)


def rank_enemy_actions(state, difficulty: AIDifficulty) -> list[ActionCandidate]:
    scored = [
        replace(candidate, score=score_enemy_action(state, candidate, difficulty))
        for candidate in get_available_enemy_actions(state)
    ]
    return sorted(scored, key=lambda candidate: candidate.score, reverse=True)


def _weighted_pick(
    ranked: list[ActionCandidate], difficulty: AIDifficulty, rng
) -> ActionCandidate:
    weights = DIFFICULTY_SELECTION.get(difficulty)
    if weights is None:
        return ranked[0]
    pool = ranked[: len(weights)]
    return rng.choices(pool, weights=weights[: len(pool)], k=1)[0]


def _select(
    ranked: list[ActionCandidate], difficulty: AIDifficulty, rng
) -> ActionCandidate:
    # 比空过更强的动作才参与抽取：简单难度可以选得差，但不该浪费整个回合不做任何事。
    # 战略空过（留能量闪避）分数高于 PASS_SCORE，靠评分自然进池，不是被塞进去的。
    usable = [candidate for candidate in ranked if candidate.score > PASS_SCORE]
    if not usable:
        return ranked[0]
    return _weighted_pick(usable, difficulty, rng)


def select_enemy_action(
    state, difficulty: AIDifficulty, rng: random.Random
) -> ActionCandidate:
    return _select(rank_enemy_actions(state, difficulty), difficulty, rng)


def choose_enemy_response(
    state, difficulty: AIDifficulty, rng: random.Random
) -> ActionCandidate:
    """电脑作为防御方的闪避 / 放弃选择。

    复用出牌的难度配置与评分，但不套用"别浪费整个回合"的过滤：
    放弃响应只是挨这一下，闪避牌还留在手里，本身就是合法选择。
    反过来要滤掉零收益的闪避：这一下全被护盾吃掉时闪避救不回任何生命，
    难度权重不该让它白扔 1 点能量和一张闪避牌——简单难度可以选得差，
    但不该浪费手里的资源，和出牌侧"不浪费整个回合"是同一个原则。
    """
    ranked = rank_enemy_responses(state, difficulty)
    usable = [
        candidate
        for candidate in ranked
        if candidate.kind == "pass" or candidate.score > 0.0
    ]
    return _weighted_pick(usable, difficulty, rng)
