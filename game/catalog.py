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
    # 装备：打出去之后留在槽里，不进弃牌堆。value 是加成 / 减伤点数。
    "longsword": CardDefinition("longsword", "长剑", 1, "equip", 2),
    "iron_armor": CardDefinition("iron_armor", "铁甲", 1, "equip", 2),
}

# 公开牌表的键：AI 的最坏情况估算只能从这里取牌，不能读对手手里有什么。
CATALOG_KEYS: tuple[str, ...] = tuple(CARDS)

# 装备 key → ParticipantState 上的槽位字段名。每张装备牌都必须在这里有归宿。
EQUIP_SLOTS: dict[str, str] = {
    "longsword": "weapon",
    "iron_armor": "armor",
}

# 长剑只强化斩击：别的伤害牌不受武器加成。
LONGSWORD_BOOST_KEYS: frozenset[str] = frozenset({"slash"})

# 三个英雄各持一副 15 张的专属牌组：打法差异来自牌组构成，不额外加规则。
# 战士牌多血厚，靠护盾和治疗拖长对局；法师三张火球抢速杀；游侠八张斩击最容易打成连击。
# 装备牌每种至多一张：长剑只进斩击多的战士和游侠，法师只带铁甲。
HERO_DECKS: dict[str, list[str]] = {
    "warrior": [
        "slash",
        "slash",
        "slash",
        "slash",
        "slash",
        "slash",
        "heavy_strike",
        "heavy_strike",
        "heavy_strike",
        "shield",
        "shield",
        "heal",
        "dodge",
        "longsword",
        "iron_armor",
    ],
    "mage": [
        "fireball",
        "fireball",
        "fireball",
        "heavy_strike",
        "heavy_strike",
        "heavy_strike",
        "slash",
        "slash",
        "slash",
        "slash",
        "shield",
        "shield",
        "heal",
        "dodge",
        "iron_armor",
    ],
    "ranger": [
        "slash",
        "slash",
        "slash",
        "slash",
        "slash",
        "slash",
        "slash",
        "slash",
        "heavy_strike",
        "heavy_strike",
        "shield",
        "heal",
        "dodge",
        "dodge",
        "longsword",
    ],
}
