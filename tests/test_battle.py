import random

from game.battle import ROUND_LIMIT, BattleState
from game.catalog import FIXED_DECK_KEYS, HEROES
from game.models import AIDifficulty, BattlePhase, Side


def make_battle(hero_key="warrior"):
    return BattleState.create(hero_key, random.Random(7), starting_side=Side.PLAYER)


def test_new_battle_has_five_cards_three_energy_and_player_turn():
    battle = make_battle()
    assert battle.phase is BattlePhase.PLAYER_TURN
    assert battle.player.hp == 32
    assert battle.enemy.hp == battle.enemy_hero.max_hp
    assert battle.player.energy == 3
    assert len(battle.hand) == 5
    assert battle.round_number == 1


def test_new_battle_assigns_two_heroes_from_the_same_roster():
    battle = BattleState.create("mage", random.Random(7), starting_side=Side.PLAYER)
    player = battle.participant(Side.PLAYER)
    enemy = battle.participant(Side.ENEMY)
    assert player.hero.key == "mage"
    assert enemy.hero.key in HEROES
    assert enemy.combatant.max_hp == HEROES[enemy.hero.key].max_hp
    assert battle.enemy_hero is enemy.hero
    assert battle.hero is player.hero


def test_participants_expose_both_sides_private_zones():
    battle = BattleState.create("ranger", random.Random(3), starting_side=Side.PLAYER)
    player = battle.participant(Side.PLAYER)
    enemy = battle.participant(Side.ENEMY)
    assert battle.opponent_of(Side.PLAYER) is enemy
    assert battle.opponent_of(Side.ENEMY) is player
    assert player.combatant is battle.player
    assert enemy.combatant is battle.enemy
    assert len(player.hand) == 5
    assert len(enemy.hand) == 5
    assert player.skill_used_this_turn is False
    assert enemy.skill_used_this_turn is False


def test_enemy_hero_does_not_depend_on_the_player_hero():
    picked = {
        BattleState.create(hero, random.Random(11)).enemy_hero.key
        for hero in ("warrior", "mage", "ranger")
    }
    assert len(picked) == 1


def test_enemy_hero_varies_across_games():
    picked = {
        BattleState.create("warrior", random.Random(seed)).enemy_hero.key
        for seed in range(20)
    }
    assert picked == set(HEROES)


def test_starting_side_is_drawn_from_the_rng_for_both_sides():
    sides = {
        BattleState.create("warrior", random.Random(seed)).starting_side
        for seed in range(20)
    }
    assert sides == {Side.PLAYER, Side.ENEMY}


def test_created_battle_never_leaves_the_enemy_turn_pending():
    for seed in range(20):
        battle = BattleState.create("warrior", random.Random(seed))
        assert battle.phase in (
            BattlePhase.PLAYER_TURN,
            BattlePhase.VICTORY,
            BattlePhase.DEFEAT,
        )


def test_starting_side_can_hand_the_first_turn_to_the_enemy():
    battle = BattleState.create("warrior", random.Random(7), starting_side=Side.ENEMY)
    assert battle.starting_side is Side.ENEMY
    # 电脑先手时，创建流程会同步跑完它这一回合，再把行动权交回玩家。
    assert any(entry.startswith("电脑使用") for entry in battle.log)
    assert battle.phase is BattlePhase.PLAYER_TURN
    assert battle.round_number == 1
    assert battle.player.energy == 3
    assert len(battle.hand) == 5


def test_both_sides_receive_the_same_fixed_deck_composition():
    battle = make_battle()
    for side in (Side.PLAYER, Side.ENEMY):
        participant = battle.participant(side)
        keys = (
            [card["key"] for card in participant.hand]
            + list(participant.draw_pile)
            + list(participant.discard_pile)
        )
        assert sorted(keys) == sorted(FIXED_DECK_KEYS)


def test_enemy_shield_persists_across_its_own_turns():
    battle = make_battle()
    battle.enemy.shield = 6
    battle.enemy_hand = []
    battle.end_player_turn()
    battle.resolve_enemy_turn()
    assert battle.enemy.shield == 6


def test_energy_carries_into_the_opponent_turn_and_refreshes_on_your_own():
    battle = make_battle()
    battle.hand = []
    battle.enemy_hand = []
    battle.player.energy = 1
    battle.end_player_turn()
    assert battle.player.energy == 1
    battle.resolve_enemy_turn()
    assert battle.player.energy == 3


def test_each_side_draws_one_card_at_the_start_of_its_own_next_turn():
    battle = make_battle()
    battle.hand = []
    battle.enemy_hand = []
    battle.end_player_turn()
    assert battle.enemy_hand == []
    battle.resolve_enemy_turn()
    assert len(battle.hand) == 1
    battle.end_player_turn()
    assert len(battle.enemy_hand) == 1


def test_skill_availability_refreshes_at_the_start_of_your_own_turn():
    battle = make_battle()
    battle.hand = []
    battle.enemy_hand = []
    assert battle.use_skill().ok is True
    assert battle.skill_used_this_turn is True
    battle.end_player_turn()
    battle.resolve_enemy_turn()
    assert battle.skill_used_this_turn is False


def test_round_limit_lets_each_side_act_ten_times():
    for first_side in (Side.PLAYER, Side.ENEMY):
        battle = BattleState.create(
            "warrior", random.Random(7), starting_side=first_side
        )
        # 电脑先手时 create() 已经替它跑完第一个回合。
        turns = {Side.PLAYER: 0, Side.ENEMY: 1 if first_side is Side.ENEMY else 0}
        for _ in range(4 * ROUND_LIMIT):
            if battle.is_finished():
                break
            if battle.phase is BattlePhase.RESPONSE:
                battle.respond("pass")
                continue
            side = (
                Side.PLAYER if battle.phase is BattlePhase.PLAYER_TURN else Side.ENEMY
            )
            turns[side] += 1
            if side is Side.PLAYER:
                battle.hand = []
                battle.end_player_turn()
            else:
                battle.enemy_hand = []
                battle.resolve_enemy_turn()
        assert battle.phase is BattlePhase.DRAW
        assert turns == {Side.PLAYER: ROUND_LIMIT, Side.ENEMY: ROUND_LIMIT}


def test_damage_uses_shield_before_health():
    battle = make_battle()
    battle.enemy.shield = 4
    hp_before = battle.enemy.hp
    battle.apply_damage(battle.enemy, 6)
    assert battle.enemy.shield == 0
    assert battle.enemy.hp == hp_before - 2


def test_playing_a_card_spends_energy_moves_card_and_writes_log():
    battle = make_battle()
    battle.hand = [{"id": "player-slash", "key": "slash"}]
    hp_before = battle.enemy.hp
    result = battle.play_card("player-slash")
    assert result.ok is True
    assert battle.player.energy == 2
    assert len(battle.hand) == 0
    assert len(battle.discard_pile) == 1
    assert battle.enemy.hp == hp_before - 6
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


def test_dodge_cannot_be_played_during_normal_player_turn():
    battle = make_battle()
    battle.hand = [{"id": "player-dodge", "key": "dodge"}]

    result = battle.play_card("player-dodge")

    assert result.ok is False
    assert result.message == "闪避只能在敌人攻击时使用"
    assert battle.player.energy == 3
    assert battle.hand == [{"id": "player-dodge", "key": "dodge"}]


def test_enemy_attack_pauses_for_available_dodge_without_dealing_damage():
    battle = make_battle()
    battle.player.energy = 2
    battle.hand = [{"id": "player-dodge", "key": "dodge"}]
    battle.enemy_hand = [{"id": "enemy-heavy", "key": "heavy_strike"}]

    battle.end_player_turn()
    result = battle.resolve_enemy_turn()

    assert result.ok is True
    assert battle.phase is BattlePhase.RESPONSE
    assert battle.player.hp == 32
    assert battle.player.energy == 2
    assert battle.pending_attack["card_name"] == "重击"
    assert battle.pending_attack["damage"] == 10


def test_using_dodge_cancels_attack_and_starts_next_player_turn():
    battle = make_battle()
    battle.player.energy = 2
    battle.hand = [{"id": "player-dodge", "key": "dodge"}]
    battle.enemy_hand = [{"id": "enemy-heavy", "key": "heavy_strike"}]
    battle.end_player_turn()
    battle.resolve_enemy_turn()

    result = battle.respond("dodge")

    assert result.ok is True
    assert battle.phase is BattlePhase.PLAYER_TURN
    assert battle.round_number == 2
    assert battle.player.hp == 32
    assert battle.player.energy == 3
    assert all(card["key"] != "dodge" for card in battle.hand)
    assert "dodge" in battle.discard_pile
    assert "玩家使用【闪避】，抵消了本次伤害" in battle.log


def test_passing_response_resolves_damage_with_shield_first():
    battle = make_battle()
    battle.player.energy = 2
    battle.player.shield = 4
    battle.hand = [{"id": "player-dodge", "key": "dodge"}]
    battle.enemy_hand = [{"id": "enemy-heavy", "key": "heavy_strike"}]
    battle.end_player_turn()
    battle.resolve_enemy_turn()

    result = battle.respond("pass")

    assert result.ok is True
    assert battle.phase is BattlePhase.PLAYER_TURN
    assert battle.player.shield == 0
    assert battle.player.hp == 26
    assert battle.player.energy == 3
    assert "电脑使用【重击】，对你造成 10 点伤害" in battle.log


def test_ai_difficulty_defaults_to_medium_and_survives_serialization():
    battle = make_battle()
    assert battle.ai_difficulty is AIDifficulty.MEDIUM
    battle.ai_difficulty = AIDifficulty.HARD
    restored = BattleState.from_dict(battle.to_dict())
    assert restored.ai_difficulty is AIDifficulty.HARD


def test_create_accepts_an_explicit_difficulty():
    battle = BattleState.create("mage", random.Random(7), AIDifficulty.EASY)
    assert battle.ai_difficulty is AIDifficulty.EASY


def test_enemy_attack_resolves_immediately_without_available_dodge():
    battle = make_battle()
    battle.player.energy = 0
    battle.hand = [{"id": "player-dodge", "key": "dodge"}]
    battle.enemy_hand = [{"id": "enemy-slash", "key": "slash"}]
    battle.end_player_turn()

    result = battle.resolve_enemy_turn()

    assert result.ok is True
    assert battle.phase is BattlePhase.PLAYER_TURN
    assert battle.player.hp == 26
    assert battle.pending_attack is None
