from game.catalog import CARDS, FIXED_DECK_KEYS, HEROES


def test_catalog_has_the_three_specified_heroes():
    assert set(HEROES) == {"warrior", "mage", "ranger"}
    assert HEROES["warrior"].max_hp == 32
    assert HEROES["mage"].max_hp == 24
    assert HEROES["ranger"].max_hp == 27


def test_fixed_deck_matches_the_twelve_card_mvp_deck():
    assert len(FIXED_DECK_KEYS) == 12
    assert FIXED_DECK_KEYS.count("slash") == 4
    assert FIXED_DECK_KEYS.count("heavy_strike") == 2
    assert FIXED_DECK_KEYS.count("shield") == 3
    assert FIXED_DECK_KEYS.count("heal") == 2
    assert FIXED_DECK_KEYS.count("fireball") == 1
    assert {card.key for card in CARDS.values()} == set(FIXED_DECK_KEYS)


def test_each_card_matches_mvp_cost_and_effect_values():
    assert len(CARDS) == 5
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
