from game.models import CardDefinition, HeroDefinition

STARTING_ENERGY = 3
SKILL_COST = 2

HEROES: dict[str, HeroDefinition] = {
    "warrior": HeroDefinition("warrior", "战士", 32, "守护", "shield", 8),
    "mage": HeroDefinition("mage", "法师", 24, "火球术", "damage", 10),
    "ranger": HeroDefinition("ranger", "游侠", 27, "连射", "damage_draw", 6),
}

CARDS: dict[str, CardDefinition] = {
    "slash": CardDefinition("slash", "斩击", 1, "damage", 6),
    "heavy_strike": CardDefinition("heavy_strike", "重击", 2, "damage", 10),
    "shield": CardDefinition("shield", "护盾", 1, "shield", 6),
    "heal": CardDefinition("heal", "治疗", 2, "heal", 6),
    "fireball": CardDefinition("fireball", "火球", 3, "damage", 14),
    "dodge": CardDefinition("dodge", "闪避", 1, "dodge", 0),
}

FIXED_DECK_KEYS: list[str] = [
    "slash",
    "slash",
    "slash",
    "slash",
    "heavy_strike",
    "heavy_strike",
    "shield",
    "shield",
    "shield",
    "heal",
    "heal",
    "fireball",
    "dodge",
]
