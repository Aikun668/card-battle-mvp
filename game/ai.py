from dataclasses import dataclass, replace
from typing import Literal

from game.catalog import CARDS
from game.models import AIDifficulty, CardDefinition

DAMAGE_KEYS = {"slash", "heavy_strike", "fireball"}
LOW_PLAYER_HP = 10
LOW_ENEMY_HP = 8
MID_ENEMY_HP = 16

# 电脑没有英雄技能，也无法主动打出只能在响应时机使用的牌。
ENEMY_UNUSABLE_EFFECTS = frozenset({"dodge"})

LETHAL_BONUS = 1000.0
EFFICIENCY_WEIGHT = 0.5
PASS_SCORE = 0.5
SHIELD_SCALE = 12.0
# 平方增长：失血越多，治疗与护盾的边际价值上升越快，濒死时自然转向自保。
RISK_WEIGHT = 6.0


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
    # 被护盾挡下的部分和超出剩余生命的部分都不产生价值。
    effective = max(0, definition.value - state.player.shield)
    useful = min(effective, state.player.hp)
    score = useful + useful / definition.cost * EFFICIENCY_WEIGHT
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


def score_enemy_action(
    state, candidate: ActionCandidate, difficulty: AIDifficulty
) -> float:
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


def rank_enemy_actions(state, difficulty: AIDifficulty) -> list[ActionCandidate]:
    scored = [
        replace(candidate, score=score_enemy_action(state, candidate, difficulty))
        for candidate in get_available_enemy_actions(state)
    ]
    return sorted(scored, key=lambda candidate: candidate.score, reverse=True)


def _card_for_key(card_instance: dict) -> CardDefinition:
    return CARDS[card_instance["key"]]


def _affordable(hand: list[dict], energy: int) -> list[tuple[dict, CardDefinition]]:
    return [(c, _card_for_key(c)) for c in hand if _card_for_key(c).cost <= energy]


def _pick_heal(hand: list[dict], energy: int) -> dict | None:
    for card, definition in _affordable(hand, energy):
        if definition.effect_type == "heal":
            return card
    return None


def _pick_shield(hand: list[dict], energy: int) -> dict | None:
    for card, definition in _affordable(hand, energy):
        if definition.effect_type == "shield":
            return card
    return None


def _pick_highest_damage(hand: list[dict], energy: int) -> dict | None:
    candidates = [
        (c, d) for c, d in _affordable(hand, energy) if d.effect_type == "damage"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[1].value, reverse=True)
    return candidates[0][0]


def choose_enemy_card(state) -> str | None:
    enemy = state.enemy
    hand = state.enemy_hand

    if enemy.hp <= LOW_ENEMY_HP:
        heal = _pick_heal(hand, enemy.energy)
        if heal is not None:
            return heal["id"]

    if state.player.hp <= LOW_PLAYER_HP:
        dmg = _pick_highest_damage(hand, enemy.energy)
        if dmg is not None:
            return dmg["id"]

    if enemy.hp <= MID_ENEMY_HP:
        shield = _pick_shield(hand, enemy.energy)
        if shield is not None:
            return shield["id"]

    dmg = _pick_highest_damage(hand, enemy.energy)
    if dmg is not None:
        return dmg["id"]

    return None
