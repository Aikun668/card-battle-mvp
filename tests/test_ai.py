import random

from game.ai import choose_enemy_card
from game.battle import BattleState


def make_battle():
    return BattleState.create("warrior", random.Random(3))


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
