import random

from game.battle import BattleState
from game.models import BattlePhase


def make_battle(hero_key="warrior"):
    return BattleState.create(hero_key, random.Random(7))


def test_new_battle_has_five_cards_three_energy_and_player_turn():
    battle = make_battle()
    assert battle.phase is BattlePhase.PLAYER_TURN
    assert battle.player.hp == 32
    assert battle.enemy.hp == 28
    assert battle.player.energy == 3
    assert len(battle.hand) == 5
    assert battle.round_number == 1


def test_damage_uses_shield_before_health():
    battle = make_battle()
    battle.enemy.shield = 4
    battle.apply_damage(battle.enemy, 6)
    assert battle.enemy.shield == 0
    assert battle.enemy.hp == 26


def test_playing_a_card_spends_energy_moves_card_and_writes_log():
    battle = make_battle()
    battle.hand = [{"id": "player-slash", "key": "slash"}]
    result = battle.play_card("player-slash")
    assert result.ok is True
    assert battle.player.energy == 2
    assert len(battle.hand) == 0
    assert len(battle.discard_pile) == 1
    assert battle.enemy.hp == 22
    assert "斩击" in battle.log[-1]


def test_insufficient_energy_does_not_mutate_battle():
    battle = make_battle()
    battle.player.energy = 1
    battle.hand = [{"id": "player-fireball", "key": "fireball"}]
    before = battle.to_dict()
    result = battle.play_card("player-fireball")
    assert result.ok is False
    assert result.message == "能量不足，还差 2 点"
    assert battle.to_dict() == before


def test_skill_can_only_be_used_once_per_player_turn():
    battle = make_battle("warrior")
    first = battle.use_skill()
    second = battle.use_skill()
    assert first.ok is True
    assert battle.player.shield == 8
    assert second.ok is False
    assert second.message == "本回合技能已经使用过"


def test_finished_battle_rejects_further_card_actions():
    battle = make_battle()
    battle.enemy.hp = 1
    battle.hand = [{"id": "player-slash", "key": "slash"}]
    assert battle.play_card("player-slash").ok is True
    result = battle.play_card("player-slash")
    assert result.ok is False
    assert result.message == "本局已经结束，请重新开始"