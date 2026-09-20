from dataclasses import dataclass
from enum import Enum


class BattlePhase(str, Enum):
    START = "START"
    HERO_SELECTION = "HERO_SELECTION"
    PLAYER_TURN = "PLAYER_TURN"
    ENEMY_TURN = "ENEMY_TURN"
    RESPONSE = "RESPONSE"
    VICTORY = "VICTORY"
    DEFEAT = "DEFEAT"
    DRAW = "DRAW"


@dataclass(frozen=True)
class CardDefinition:
    key: str
    name: str
    cost: int
    effect_type: str
    value: int


@dataclass(frozen=True)
class HeroDefinition:
    key: str
    name: str
    max_hp: int
    skill_name: str
    skill_type: str
    skill_value: int


@dataclass
class Combatant:
    name: str
    max_hp: int
    hp: int
    shield: int = 0
    energy: int = 3


@dataclass
class ActionResult:
    ok: bool
    message: str
