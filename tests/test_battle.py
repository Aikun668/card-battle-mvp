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


def test_damage_clamps_hp_at_zero():
    battle = make_battle()
    battle.apply_damage(battle.player, 9999)
    assert battle.player.hp == 0
    assert battle.player.shield == 0


def test_heal_clamps_at_max_hp():
    battle = make_battle()
    battle.player.hp = 30
    battle.apply_heal(battle.player, 10)
    assert battle.player.hp == 32


def test_playing_card_not_in_hand_returns_message():
    battle = make_battle()
    result = battle.play_card("card-not-in-hand")
    assert result.ok is False
    assert result.message == "这张卡牌已经不能使用"


def test_hand_limit_is_six_and_logs_when_full():
    battle = make_battle()
    battle.discard_pile.clear()
    battle.draw_pile = ["slash"] * 30
    battle.hand = [{"id": f"x{i}", "key": "slash"} for i in range(6)]
    drawn = battle.draw_cards(3)
    assert drawn == 0
    assert len(battle.hand) == 6
    assert any("手牌已满" in entry for entry in battle.log)


def test_draw_pile_exhausted_reshuffles_discard_only_when_discard_exists():
    battle = make_battle()
    battle.draw_pile = []
    battle.discard_pile = ["slash", "heal", "shield"]
    drawn = battle.draw_cards(2)
    assert drawn == 1  # first draw reshuffles, hand reaches limit 6, second blocked
    assert len(battle.hand) == 6
    # discard was moved into draw_pile then one was drawn; 2 left in draw, 0 in discard
    assert len(battle.draw_pile) == 2
    assert len(battle.discard_pile) == 0


def test_draw_pile_empty_with_no_discard_draws_nothing():
    battle = make_battle()
    battle.draw_pile = []
    battle.discard_pile = []
    drawn = battle.draw_cards(3)
    assert drawn == 0


def test_round_ten_ends_in_draw():
    battle = make_battle()
    battle.round_number = 10
    battle.enemy_hand = [{"id": "enemy-slash", "key": "slash"}]
    battle.end_player_turn()
    battle.resolve_enemy_turn()
    assert battle.phase.value == "DRAW"
    assert battle.is_finished()


def test_terminal_state_rejects_end_turn_and_skill():
    battle = make_battle()
    battle.enemy.hp = 1
    battle.hand = [{"id": "player-slash", "key": "slash"}]
    battle.play_card("player-slash")
    assert battle.end_player_turn().ok is False
    assert battle.use_skill().ok is False


def test_player_action_rejected_during_enemy_turn():
    battle = make_battle()
    battle.hand = [{"id": "player-slash", "key": "slash"}]
    battle.end_player_turn()
    result = battle.play_card("player-slash")
    assert result.ok is False
    assert result.message == "现在是电脑回合，请等待电脑行动"
    result_skill = battle.use_skill()
    assert result_skill.ok is False
    assert result_skill.message == "现在是电脑回合，请等待电脑行动"
