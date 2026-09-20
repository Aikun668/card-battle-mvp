import random

from game.ai import (
    choose_enemy_card,
    get_available_enemy_actions,
    rank_enemy_actions,
)
from game.battle import BattleState
from game.models import AIDifficulty


def make_battle():
    return BattleState.create("warrior", random.Random(3))


# --- Task 2: utility scoring ---


def test_lethal_heavy_strike_outranks_overkill_fireball():
    battle = make_battle()
    battle.player.hp = 8
    battle.player.shield = 0
    battle.enemy.energy = 3
    battle.enemy_hand = [
        {"id": "heavy", "key": "heavy_strike"},
        {"id": "fireball", "key": "fireball"},
    ]
    ranked = rank_enemy_actions(battle, AIDifficulty.HARD)
    assert ranked[0].card_id == "heavy"


def test_heal_near_max_health_scores_below_damage():
    battle = make_battle()
    battle.enemy.hp = battle.enemy.max_hp - 1
    battle.enemy_hand = [
        {"id": "heal", "key": "heal"},
        {"id": "slash", "key": "slash"},
    ]
    ranked = rank_enemy_actions(battle, AIDifficulty.MEDIUM)
    assert ranked[0].card_id == "slash"


def test_existing_shield_makes_further_shield_score_below_attack():
    battle = make_battle()
    battle.enemy.hp = battle.enemy.max_hp
    battle.enemy.shield = 12
    battle.enemy_hand = [
        {"id": "shield", "key": "shield"},
        {"id": "slash", "key": "slash"},
    ]
    ranked = rank_enemy_actions(battle, AIDifficulty.MEDIUM)
    assert ranked[0].card_id == "slash"


def test_actual_healing_outranks_plain_attack_when_hurt_and_no_kill_exists():
    battle = make_battle()
    battle.enemy.hp = 10
    battle.player.hp = battle.player.max_hp
    battle.enemy_hand = [
        {"id": "heal", "key": "heal"},
        {"id": "slash", "key": "slash"},
    ]
    ranked = rank_enemy_actions(battle, AIDifficulty.MEDIUM)
    assert ranked[0].card_id == "heal"


def test_attack_through_shield_only_scores_the_damage_that_lands():
    battle = make_battle()
    battle.enemy.hp = battle.enemy.max_hp
    battle.player.hp = battle.player.max_hp
    battle.player.shield = 6
    battle.enemy.energy = 3
    battle.enemy_hand = [
        {"id": "slash", "key": "slash"},
        {"id": "heavy", "key": "heavy_strike"},
    ]
    ranked = rank_enemy_actions(battle, AIDifficulty.MEDIUM)
    assert ranked[0].card_id == "heavy"


def test_a_dying_enemy_defends_instead_of_trading_damage():
    battle = make_battle()
    battle.enemy.hp = 6
    battle.player.hp = battle.player.max_hp
    battle.enemy_hand = [
        {"id": "fireball", "key": "fireball"},
        {"id": "heal", "key": "heal"},
    ]
    ranked = rank_enemy_actions(battle, AIDifficulty.MEDIUM)
    assert ranked[0].card_id == "heal"


def test_pass_ranks_last_when_a_useful_action_exists():
    battle = make_battle()
    battle.enemy_hand = [{"id": "slash", "key": "slash"}]
    ranked = rank_enemy_actions(battle, AIDifficulty.MEDIUM)
    assert ranked[-1].kind == "pass"


def test_pass_outranks_a_heal_that_would_restore_nothing():
    battle = make_battle()
    battle.enemy.hp = battle.enemy.max_hp
    battle.enemy_hand = [{"id": "heal", "key": "heal"}]
    ranked = rank_enemy_actions(battle, AIDifficulty.MEDIUM)
    assert ranked[0].kind == "pass"


def test_ranking_does_not_mutate_the_battle():
    battle = make_battle()
    battle.enemy_hand = [{"id": "slash", "key": "slash"}]
    before = battle.to_dict()
    rank_enemy_actions(battle, AIDifficulty.MEDIUM)
    assert battle.to_dict() == before


def test_available_enemy_actions_include_affordable_cards_and_pass():
    battle = make_battle()
    battle.enemy_hand = [{"id": "enemy-slash", "key": "slash"}]
    actions = get_available_enemy_actions(battle)
    assert {action.kind for action in actions} == {"card", "pass"}
    assert any(action.card_id == "enemy-slash" for action in actions)


def test_unaffordable_cards_are_not_candidates():
    battle = make_battle()
    battle.enemy.energy = 1
    battle.enemy_hand = [{"id": "enemy-fireball", "key": "fireball"}]
    actions = get_available_enemy_actions(battle)
    assert all(action.kind != "card" for action in actions)


def test_dodge_is_never_an_enemy_candidate():
    battle = make_battle()
    battle.enemy_hand = [{"id": "enemy-dodge", "key": "dodge"}]
    actions = get_available_enemy_actions(battle)
    assert all(action.kind != "card" for action in actions)


def test_pass_is_available_even_with_an_empty_hand():
    battle = make_battle()
    battle.enemy_hand = []
    actions = get_available_enemy_actions(battle)
    assert [action.kind for action in actions] == ["pass"]


def test_candidate_generation_does_not_mutate_the_battle():
    battle = make_battle()
    battle.enemy_hand = [{"id": "enemy-slash", "key": "slash"}]
    before = battle.to_dict()
    get_available_enemy_actions(battle)
    assert battle.to_dict() == before


def test_ai_heals_when_its_health_is_at_or_below_eight():
    battle = make_battle()
    battle.enemy.hp = 8
    battle.enemy_hand = [
        {"id": "enemy-heal", "key": "heal"},
        {"id": "enemy-slash", "key": "slash"},
    ]
    assert choose_enemy_card(battle) == "enemy-heal"


def test_ai_uses_highest_damage_when_player_is_low():
    battle = make_battle()
    battle.player.hp = 10
    battle.enemy_hand = [
        {"id": "enemy-slash", "key": "slash"},
        {"id": "enemy-fireball", "key": "fireball"},
    ]
    assert choose_enemy_card(battle) == "enemy-fireball"


def test_ai_uses_shield_when_low_health_and_no_heal_available():
    battle = make_battle()
    battle.enemy.hp = 14
    battle.player.hp = 24
    battle.enemy_hand = [
        {"id": "enemy-shield", "key": "shield"},
        {"id": "enemy-slash", "key": "slash"},
    ]
    assert choose_enemy_card(battle) == "enemy-shield"


def test_ai_uses_highest_damage_by_default():
    battle = make_battle()
    battle.enemy.hp = 24
    battle.player.hp = 24
    battle.enemy_hand = [
        {"id": "enemy-slash", "key": "slash"},
        {"id": "enemy-fireball", "key": "fireball"},
        {"id": "enemy-heavy", "key": "heavy_strike"},
    ]
    assert choose_enemy_card(battle) == "enemy-fireball"


def test_ai_returns_none_when_no_affordable_card():
    battle = make_battle()
    battle.enemy.energy = 0
    battle.enemy_hand = [
        {"id": "enemy-slash", "key": "slash"},
        {"id": "enemy-fireball", "key": "fireball"},
    ]
    assert choose_enemy_card(battle) is None


def test_end_turn_runs_one_enemy_action_then_returns_to_player():
    battle = make_battle()
    battle.enemy_hand = [{"id": "enemy-slash", "key": "slash"}]
    initial_hp = battle.player.hp
    assert battle.end_player_turn().ok is True
    result = battle.resolve_enemy_turn()
    assert result.ok is True
    assert battle.player.hp == initial_hp - 6
    assert battle.phase.value == "PLAYER_TURN"
    assert battle.round_number == 2
    assert battle.player.energy == 3
    assert battle.skill_used_this_turn is False


def test_resolve_enemy_turn_with_no_affordable_card_still_returns_to_player():
    battle = make_battle()
    battle.enemy_hand = []
    battle.end_player_turn()
    battle.resolve_enemy_turn()
    assert battle.phase.value == "PLAYER_TURN"
    assert battle.player.hp == 32  # undamaged
