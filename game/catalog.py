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
    # 条件牌：看局面生效，让"现在打还是留着"变成一次选择。
    "armor_break": CardDefinition("armor_break", "破甲", 1, "damage", 4),
    "charge": CardDefinition("charge", "蓄力", 1, "charge", 2),
    "execute": CardDefinition("execute", "处决", 2, "damage", 8),
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

# 条件伤害规则：目标满足条件时按增量或倍率调整。
# 结算是唯一入口，AI 评分与连招规划都必须调 conditional_damage()，
# 保证"电脑以为这一下打多少"和"真实结算打多少"永远一致。
WOUNDED_HP_RATIO = 0.3
CONDITIONAL_DAMAGE: dict[str, tuple[str, float]] = {
    "armor_break": ("target_shielded", 4),
    "execute": ("target_wounded", 2.0),
}

# 消耗牌：打出后从本局移除——不进弃牌堆、洗牌也回不来。"用掉就没了"
# 让时机本身变成资源；机制是通用的，想给更多牌加消耗往这里加 key。
EXHAUST_KEYS: frozenset[str] = frozenset({"execute"})


def conditional_damage(
    base: int,
    card_key: str,
    *,
    target_shield: int,
    target_hp: int,
    target_max_hp: int,
) -> int:
    """把卡牌的基础伤害换算成"对当前目标实际生效"的伤害。

    没有条件规则的牌原样返回；斩杀线按目标的最大生命算，严格小于才触发。
    """
    rule = CONDITIONAL_DAMAGE.get(card_key)
    if rule is None:
        return base
    condition, modifier = rule
    if condition == "target_shielded":
        return base + int(modifier) if target_shield > 0 else base
    if condition == "target_wounded":
        wounded = target_max_hp > 0 and target_hp < target_max_hp * WOUNDED_HP_RATIO
        return int(base * modifier) if wounded else base
    return base


# 三个英雄各持一副 16 张的专属牌组：打法差异来自牌组构成，不额外加规则。
# 战士牌多血厚，靠护盾和治疗拖长对局；法师三张火球抢速杀；游侠八张斩击最容易打成连击。
# 装备牌每种至多一张：长剑只进斩击多的战士和游侠，法师只带铁甲。
# 每副牌另有一张专属条件牌：战士破甲（惩罚叠盾）、法师蓄力（攒下回合能量）、
# 游侠处决（收割残血）。
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
        "armor_break",
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
        "charge",
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
        "execute",
    ],
}
