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