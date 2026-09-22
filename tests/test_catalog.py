from collections import Counter

from game.catalog import (
    CARDS,
    CONDITIONAL_DAMAGE,
    EQUIP_SLOTS,
    EXHAUST_KEYS,
    HERO_DECKS,
    HEROES,
    conditional_damage,
)


def test_catalog_has_the_three_specified_heroes():
    assert set(HEROES) == {"warrior", "mage", "ranger"}
    assert HEROES["warrior"].max_hp == 32
    assert HEROES["mage"].max_hp == 24
    assert HEROES["ranger"].max_hp == 27


def test_every_hero_has_a_sixteen_card_deck_drawn_from_the_catalog():
    assert set(HERO_DECKS) == set(HEROES)
    catalog_keys = {card.key for card in CARDS.values()}
    for hero_key, deck in HERO_DECKS.items():
        assert len(deck) == 16, hero_key
        assert set(deck) <= catalog_keys, hero_key
    # 每张定义过的牌都至少要有一副牌组在用，否则就是把废牌写进了公开牌表。
    assert set().union(*HERO_DECKS.values()) == catalog_keys


def test_hero_decks_are_the_agreed_archetypes():
    assert Counter(HERO_DECKS["warrior"]) == Counter(
        slash=6,
        heavy_strike=3,
        shield=2,
        heal=1,
        dodge=1,
        longsword=1,
        iron_armor=1,
        armor_break=1,
    )
    assert Counter(HERO_DECKS["mage"]) == Counter(
        fireball=3,
        heavy_strike=3,
        slash=4,
        shield=2,
        heal=1,
        dodge=1,
        iron_armor=1,
        charge=1,
    )
    assert Counter(HERO_DECKS["ranger"]) == Counter(
        slash=8,
        heavy_strike=2,
        shield=1,
        heal=1,
        dodge=2,
        longsword=1,
        execute=1,
    )


def test_equipment_cards_appear_at_most_once_per_deck():
    for hero_key, deck in HERO_DECKS.items():
        equipment = [key for key in deck if CARDS[key].effect_type == "equip"]
        assert len(equipment) == len(set(equipment)), hero_key


def test_equipment_cards_cost_one_energy_and_carry_their_bonus_value():
    assert CARDS["longsword"].name == "长剑"
    assert CARDS["longsword"].cost == 1
    assert CARDS["longsword"].effect_type == "equip"
    assert CARDS["longsword"].value == 2
    assert CARDS["iron_armor"].name == "铁甲"
    assert CARDS["iron_armor"].cost == 1
    assert CARDS["iron_armor"].effect_type == "equip"
    assert CARDS["iron_armor"].value == 2


def test_every_equipment_card_has_a_slot_to_land_in():
    equips = {key for key, card in CARDS.items() if card.effect_type == "equip"}
    assert set(EQUIP_SLOTS) == equips
    assert set(EQUIP_SLOTS.values()) == {"weapon", "armor"}


def test_each_card_matches_its_cost_and_effect_values():
    assert len(CARDS) == 11
    assert CARDS["slash"].cost == 1 and CARDS["slash"].value == 6
    assert CARDS["slash"].effect_type == "damage"
    assert CARDS["heavy_strike"].cost == 2 and CARDS["heavy_strike"].value == 10
    assert CARDS["heavy_strike"].effect_type == "damage"
    assert CARDS["shield"].cost == 1 and CARDS["shield"].value == 6
    assert CARDS["shield"].effect_type == "shield"
    assert CARDS["heal"].cost == 2 and CARDS["heal"].value == 6
    assert CARDS["heal"].effect_type == "heal"
    assert CARDS["fireball"].cost == 3 and CARDS["fireball"].value == 14
    assert CARDS["fireball"].effect_type == "damage"
    assert CARDS["dodge"].cost == 1 and CARDS["dodge"].value == 0
    assert CARDS["dodge"].effect_type == "dodge"


def test_conditional_cards_match_their_cost_and_effect_values():
    assert CARDS["armor_break"].name == "破甲"
    assert CARDS["armor_break"].cost == 1
    assert CARDS["armor_break"].effect_type == "damage"
    assert CARDS["armor_break"].value == 4
    assert CARDS["charge"].name == "蓄力"
    assert CARDS["charge"].cost == 1
    assert CARDS["charge"].effect_type == "charge"
    assert CARDS["charge"].value == 2
    assert CARDS["execute"].name == "处决"
    assert CARDS["execute"].cost == 2
    assert CARDS["execute"].effect_type == "damage"
    assert CARDS["execute"].value == 8


def test_each_hero_owns_exactly_one_conditional_card():
    assert HERO_DECKS["warrior"].count("armor_break") == 1
    assert HERO_DECKS["mage"].count("charge") == 1
    assert HERO_DECKS["ranger"].count("execute") == 1
    # 条件牌只此一份，别的牌组的构成不受影响。
    assert HERO_DECKS["warrior"].count("charge") == 0
    assert HERO_DECKS["ranger"].count("armor_break") == 0
    assert HERO_DECKS["mage"].count("execute") == 0


def test_conditional_damage_rules_cover_exactly_the_conditional_cards():
    """有条件伤害的牌必须都在规则表里，规则表里也不许有幽灵牌。"""
    assert set(CONDITIONAL_DAMAGE) == {"armor_break", "execute"}


def test_armor_break_punishes_shields():
    assert (
        conditional_damage(
            CARDS["armor_break"].value,
            "armor_break",
            target_shield=0,
            target_hp=30,
            target_max_hp=32,
        )
        == 4
    )
    assert (
        conditional_damage(
            CARDS["armor_break"].value,
            "armor_break",
            target_shield=6,
            target_hp=30,
            target_max_hp=32,
        )
        == 8
    )


def test_execute_doubles_below_thirty_percent_health():
    # 24 点上限：30% 的线是 7.2——7 点触发、8 点不触发（严格小于）。
    assert (
        conditional_damage(
            CARDS["execute"].value,
            "execute",
            target_shield=0,
            target_hp=8,
            target_max_hp=24,
        )
        == 8
    )
    assert (
        conditional_damage(
            CARDS["execute"].value,
            "execute",
            target_shield=0,
            target_hp=7,
            target_max_hp=24,
        )
        == 16
    )


def test_exhaust_rules_cover_exactly_the_exhaust_cards():
    """用掉就移除的牌只此一处登记；「保留」本来就是人手一张的常态。"""
    assert set(EXHAUST_KEYS) == {"execute"}


def test_conditional_damage_leaves_plain_cards_alone():
    assert (
        conditional_damage(
            CARDS["slash"].value,
            "slash",
            target_shield=12,
            target_hp=1,
            target_max_hp=24,
        )
        == 6
    )
    assert (
        conditional_damage(
            CARDS["heavy_strike"].value,
            "heavy_strike",
            target_shield=0,
            target_hp=1,
            target_max_hp=24,
        )
        == 10
    )
