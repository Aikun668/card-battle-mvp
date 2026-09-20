from dataclasses import dataclass
from typing import Literal

from game.catalog import CARDS
from game.models import CardDefinition

DAMAGE_KEYS = {"slash", "heavy_strike", "fireball"}
LOW_PLAYER_HP = 10
LOW_ENEMY_HP = 8
MID_ENEMY_HP = 16

# 电脑没有英雄技能，也无法主动打出只能在响应时机使用的牌。
ENEMY_UNUSABLE_EFFECTS = frozenset({"dodge"})


@dataclass(frozen=True)
class ActionCandidate:
    kind: Literal["card", "skill", "pass"]
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
