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


class Side(str, Enum):
    PLAYER = "player"
    ENEMY = "enemy"


class AIDifficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"

    @classmethod
    def parse(cls, value: object) -> "AIDifficulty | None":
        """把外部传入的难度值转成枚举，无法识别时返回 None。"""
        if isinstance(value, str) and value in {item.value for item in cls}:
            return cls(value)
        return None


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
class ParticipantState:
    hero: HeroDefinition
    combatant: Combatant
    hand: list[dict]
    draw_pile: list[str]
    discard_pile: list[str]
    skill_used_this_turn: bool = False
    # 装备槽：打出的装备牌留在这里，不进弃牌堆，跨回合保留。
    weapon: CardDefinition | None = None
    armor: CardDefinition | None = None
    weapon_used_this_turn: bool = False
    armor_used_this_turn: bool = False
    # 蓄力结余：下个自己的回合开始时额外获得的能量，结算后清零。
    bonus_energy_next_turn: int = 0


@dataclass(frozen=True)
class PendingAttack:
    """一次等待响应窗口的伤害攻击；费用与弃牌在挂起前就已经结清。"""

    attacker: Side
    defender: Side
    card_key: str
    card_name: str
    damage: int


@dataclass
class ActionResult:
    ok: bool
    message: str
