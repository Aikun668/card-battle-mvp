from collections import Counter

from game.catalog import CARDS, EQUIP_SLOTS, HERO_DECKS, HEROES


def test_catalog_has_the_three_specified_heroes():
    assert set(HEROES) == {"warrior", "mage", "ranger"}
    assert HEROES["warrior"].max_hp == 32
    assert HEROES["mage"].max_hp == 24
    assert HEROES["ranger"].max_hp == 27


def test_every_hero_has_a_fifteen_card_deck_drawn_from_the_catalog():
    assert set(HERO_DECKS) == set(HEROES)
    catalog_keys = {card.key for card in CARDS.values()}
    for hero_key, deck in HERO_DECKS.items():
        assert len(deck) == 15, hero_key
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
    )
    assert Counter(HERO_DECKS["mage"]) == Counter(
        fireball=3,
        heavy_strike=3,
        slash=4,
        shield=2,
        heal=1,
        dodge=1,
        iron_armor=1,
    )
    assert Counter(HERO_DECKS["ranger"]) == Counter(
        slash=8,
        heavy_strike=2,
        shield=1,
        heal=1,
        dodge=2,
        longsword=1,
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


def test_each_card_matches_mvp_cost_and_effect_values():
    assert len(CARDS) == 8
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
