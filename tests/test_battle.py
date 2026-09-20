import random
from collections import Counter

from game.battle import ROUND_LIMIT, BattleState
from game.catalog import CARDS, FIXED_DECK_KEYS, HEROES
from game.models import AIDifficulty, BattlePhase, PendingAttack, Side


def make_battle(hero_key="warrior"):
    return BattleState.create(hero_key, random.Random(7), starting_side=Side.PLAYER)


def withhold_enemy_skill(battle):
    """让电脑只出普通牌：技能标记为已用。

    电脑回合开始时 start_turn() 会重置这个标记，所以只在跑电脑回合的用例里、
    调用 end_player_turn() 之后再屏蔽。
    """
    battle.participants[Side.ENEMY].skill_used_this_turn = True
    return battle


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
    withhold_enemy_skill(battle)
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
                # 只数回合数，不让电脑的技能把玩家打死影响上限判定。
                battle.enemy_hand = []
                withhold_enemy_skill(battle)
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
    # 电脑手里有闪避就会开响应窗口，这里要验证的是伤害当场结算。
    battle.enemy_hand = []
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
    battle.enemy_hand = []
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
    battle.enemy_hand = []
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
    withhold_enemy_skill(battle)
    result = battle.resolve_enemy_turn()

    assert result.ok is True
    assert battle.phase is BattlePhase.RESPONSE
    assert battle.player.hp == 32
    assert battle.player.energy == 2
    assert battle.pending_attack.card_name == "重击"
    assert battle.pending_attack.damage == 10


def test_using_dodge_cancels_attack_and_starts_next_player_turn():
    battle = make_battle()
    battle.player.energy = 2
    battle.hand = [{"id": "player-dodge", "key": "dodge"}]
    battle.enemy_hand = [{"id": "enemy-heavy", "key": "heavy_strike"}]
    battle.end_player_turn()
    withhold_enemy_skill(battle)
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
    withhold_enemy_skill(battle)
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
    withhold_enemy_skill(battle)

    result = battle.resolve_enemy_turn()

    assert result.ok is True
    assert battle.phase is BattlePhase.PLAYER_TURN
    assert battle.player.hp == 26
    assert battle.pending_attack is None


# --- Task 3: 双方共享的卡牌、技能与结束行动 ---


def pin_enemy_hero(battle, hero_key):
    """固定电脑英雄，避免随机英雄让技能断言漂移。"""
    battle.participants[Side.ENEMY].hero = HEROES[hero_key]
    return battle


def freeze_enemy_piles(battle):
    """清空电脑两个牌区：它这一回合补不到新牌，手牌完全由测试决定。"""
    battle.enemy_hand = []
    battle.enemy_draw_pile = []
    battle.enemy_discard_pile = []
    return battle


def test_shared_actions_reject_the_side_that_is_not_acting():
    battle = make_battle()

    results = (
        battle.play_card_for(Side.ENEMY, "enemy-slash"),
        battle.use_skill_for(Side.ENEMY),
        battle.end_turn_for(Side.ENEMY),
    )

    for result in results:
        assert result.ok is False
        assert result.message == "现在不是电脑的回合"


def test_play_card_for_resolves_a_card_for_either_side():
    battle = make_battle()
    battle.hand = []
    battle.enemy_hand = [{"id": "enemy-slash", "key": "slash"}]
    battle.end_player_turn()
    hp_before = battle.player.hp

    result = battle.play_card_for(Side.ENEMY, "enemy-slash")

    assert result.ok is True
    assert battle.player.hp == hp_before - 6
    assert battle.enemy.energy == 2
    assert "电脑使用【斩击】，对你造成 6 点伤害" in battle.log


def test_end_turn_for_advances_the_turn_for_either_side():
    battle = make_battle()
    battle.hand = []

    assert battle.end_turn_for(Side.PLAYER).ok is True
    assert battle.phase is BattlePhase.ENEMY_TURN

    freeze_enemy_piles(battle)

    assert battle.end_turn_for(Side.ENEMY).ok is True
    assert battle.phase is BattlePhase.PLAYER_TURN
    assert battle.round_number == 2
    assert battle.player.energy == 3


def test_enemy_can_use_its_own_hero_skill_once_per_turn():
    battle = pin_enemy_hero(make_battle("warrior"), "mage")
    battle.ai_difficulty = AIDifficulty.HARD
    battle.hand = []
    freeze_enemy_piles(battle)
    battle.end_player_turn()

    result = battle.resolve_enemy_turn()

    assert result.ok is True
    assert battle.player.hp == 32 - 10
    assert battle.enemy.energy == 1
    assert battle.participant(Side.ENEMY).skill_used_this_turn is True
    assert "电脑释放技能【火球术】，对你造成 10 点伤害" in battle.log


def test_enemy_warrior_skill_shields_instead_of_attacking():
    battle = pin_enemy_hero(make_battle("mage"), "warrior")
    battle.ai_difficulty = AIDifficulty.HARD
    battle.hand = []
    freeze_enemy_piles(battle)
    battle.end_player_turn()

    battle.resolve_enemy_turn()

    assert battle.enemy.shield == 8
    assert battle.player.hp == battle.player.max_hp


def test_enemy_ranger_skill_damages_and_draws_a_card():
    battle = pin_enemy_hero(make_battle("warrior"), "ranger")
    battle.hand = []
    battle.enemy_hand = []
    battle.end_player_turn()
    # 回合开始的补牌已经错过，这张留给技能自己抽。
    battle.enemy_draw_pile = ["slash"]
    hp_before = battle.player.hp

    result = battle.use_skill_for(Side.ENEMY)

    assert result.ok is True
    assert battle.player.hp == hp_before - 6
    assert [card["key"] for card in battle.enemy_hand] == ["slash"]
    assert battle.enemy.energy == 1


def test_enemy_skill_and_cards_share_the_same_three_energy():
    battle = pin_enemy_hero(make_battle("warrior"), "mage")
    battle.ai_difficulty = AIDifficulty.HARD
    battle.hand = []
    freeze_enemy_piles(battle)
    battle.end_player_turn()
    battle.enemy_hand = [{"id": "enemy-slash", "key": "slash"}]

    battle.resolve_enemy_turn()

    # 火球术花掉 2 点，剩 1 点刚好够斩击，两次行动共用同一份能量。
    assert battle.enemy.energy == 0
    assert battle.player.hp == 32 - 10 - 6


def test_enemy_skill_cannot_be_used_twice_in_the_same_turn():
    battle = pin_enemy_hero(make_battle("warrior"), "mage")
    battle.hand = []
    freeze_enemy_piles(battle)
    battle.end_player_turn()

    assert battle.use_skill_for(Side.ENEMY).ok is True
    second = battle.use_skill_for(Side.ENEMY)

    assert second.ok is False
    assert second.message == "本回合技能已经使用过"


# --- Task 4: 双方对等的攻击响应 ---


def test_enemy_can_dodge_a_player_attack_with_retained_energy():
    battle = make_battle()
    battle.ai_difficulty = AIDifficulty.HARD
    battle.enemy.energy = 1
    battle.enemy_hand = [{"id": "enemy-dodge", "key": "dodge"}]
    battle.hand = [{"id": "player-heavy", "key": "heavy_strike"}]
    before = battle.enemy.hp

    result = battle.play_card("player-heavy")

    assert result.ok is True
    assert battle.enemy.hp == before
    assert battle.enemy.energy == 0
    assert "dodge" in battle.enemy_discard_pile
    assert battle.pending_attack is None
    assert battle.enemy_hand == []


def test_enemy_without_energy_cannot_dodge_and_takes_the_damage():
    battle = make_battle()
    battle.ai_difficulty = AIDifficulty.HARD
    battle.enemy.energy = 0
    battle.enemy_hand = [{"id": "enemy-dodge", "key": "dodge"}]
    battle.hand = [{"id": "player-slash", "key": "slash"}]
    before = battle.enemy.hp

    battle.play_card("player-slash")

    assert battle.enemy.hp == before - 6
    assert [card["key"] for card in battle.enemy_hand] == ["dodge"]
    assert battle.pending_attack is None


def test_one_attack_opens_exactly_one_response_window():
    battle = make_battle()
    battle.ai_difficulty = AIDifficulty.HARD
    battle.enemy.energy = 1
    battle.enemy_hand = [{"id": "enemy-dodge", "key": "dodge"}]
    battle.hand = [{"id": "player-slash", "key": "slash"}]

    battle.play_card("player-slash")

    # 电脑用掉唯一一张闪避之后，这次攻击没有第二个响应窗口。
    later = battle.respond("dodge")
    assert later.ok is False
    assert later.message == "当前没有需要响应的攻击"
    assert battle.pending_attack is None


def test_player_keeps_the_turn_after_the_enemy_dodges():
    battle = make_battle()
    battle.ai_difficulty = AIDifficulty.HARD
    battle.enemy.energy = 1
    battle.enemy_hand = [{"id": "enemy-dodge", "key": "dodge"}]
    battle.hand = [
        {"id": "player-slash", "key": "slash"},
        {"id": "player-heavy", "key": "heavy_strike"},
    ]
    before = battle.enemy.hp

    assert battle.play_card("player-slash").ok is True
    assert battle.phase is BattlePhase.PLAYER_TURN

    # 闪避没有中断玩家自己的行动回合，他还能接着打出第二张牌。
    assert battle.play_card("player-heavy").ok is True
    assert battle.enemy.hp == before - 10
    assert battle.player.energy == 0


def test_responding_for_the_wrong_side_is_rejected():
    battle = make_battle()
    battle.hand = [{"id": "player-dodge", "key": "dodge"}]
    battle.enemy_hand = [{"id": "enemy-heavy", "key": "heavy_strike"}]
    battle.end_player_turn()
    withhold_enemy_skill(battle)
    battle.resolve_enemy_turn()

    result = battle.respond_for(Side.ENEMY, "dodge")

    assert result.ok is False
    assert result.message == "这次攻击不是针对你的"
    assert battle.phase is BattlePhase.RESPONSE


# --- Task 2: 装备结算 ---


def wear_gear(battle, side, card_key):
    """直接给某一方穿上装备：这些用例测的是结算规则，不是打牌流程。"""
    participant = battle.participant(side)
    if card_key == "longsword":
        participant.weapon = CARDS[card_key]
    else:
        participant.armor = CARDS[card_key]
    return battle


def test_equipping_puts_the_card_into_the_slot_and_never_into_the_discard_pile():
    battle = make_battle()
    battle.hand = [{"id": "player-sword", "key": "longsword"}]

    result = battle.play_card("player-sword")

    assert result.ok is True
    participant = battle.participant(Side.PLAYER)
    assert participant.weapon.key == "longsword"
    assert participant.discard_pile == []
    assert participant.combatant.energy == 2
    assert battle.phase is BattlePhase.PLAYER_TURN
    assert "长剑" in battle.log[-1]


def test_the_armor_card_lands_in_the_armor_slot():
    battle = make_battle()
    battle.hand = [{"id": "player-armor", "key": "iron_armor"}]

    assert battle.play_card("player-armor").ok is True

    participant = battle.participant(Side.PLAYER)
    assert participant.armor.key == "iron_armor"
    assert participant.weapon is None
    assert participant.discard_pile == []


def test_equipping_costs_energy_like_any_other_card():
    battle = make_battle()
    battle.player.energy = 0
    battle.hand = [{"id": "player-sword", "key": "longsword"}]

    result = battle.play_card("player-sword")

    assert result.ok is False
    assert result.message == "能量不足，还差 1 点"
    assert battle.participant(Side.PLAYER).weapon is None
    assert battle.hand == [{"id": "player-sword", "key": "longsword"}]


def test_equipping_during_the_other_sides_turn_is_rejected():
    battle = make_battle()
    battle.hand = [{"id": "player-sword", "key": "longsword"}]
    battle.end_player_turn()

    result = battle.play_card("player-sword")

    assert result.ok is False
    assert result.message == "现在是电脑回合，请等待电脑行动"
    assert battle.participant(Side.PLAYER).weapon is None
    assert battle.player.energy == 3


def test_equipping_never_opens_a_response_window():
    battle = make_battle()
    battle.enemy.energy = 1
    battle.enemy_hand = [{"id": "enemy-dodge", "key": "dodge"}]
    battle.hand = [{"id": "player-sword", "key": "longsword"}]

    assert battle.play_card("player-sword").ok is True

    assert battle.phase is BattlePhase.PLAYER_TURN
    assert battle.pending_attack is None
    assert battle.enemy_hand == [{"id": "enemy-dodge", "key": "dodge"}]


def test_the_enemy_side_equips_through_the_same_path():
    battle = make_battle()
    battle.hand = []
    battle.end_player_turn()
    battle.enemy_hand = [{"id": "enemy-sword", "key": "longsword"}]

    result = battle.play_card_for(Side.ENEMY, "enemy-sword")

    assert result.ok is True
    enemy = battle.participant(Side.ENEMY)
    assert enemy.weapon.key == "longsword"
    assert enemy.discard_pile == []
    assert enemy.combatant.energy == 2


def test_the_weapon_boosts_only_the_first_slash_of_its_owners_turn():
    battle = wear_gear(make_battle(), Side.PLAYER, "longsword")
    battle.enemy_hand = []
    battle.hand = [{"id": "slash-1", "key": "slash"}, {"id": "slash-2", "key": "slash"}]
    before = battle.enemy.hp

    assert battle.play_card("slash-1").ok is True
    assert battle.enemy.hp == before - 8
    assert battle.play_card("slash-2").ok is True
    assert battle.enemy.hp == before - 14


def test_the_weapon_never_boosts_anything_but_a_slash():
    battle = wear_gear(make_battle(), Side.PLAYER, "longsword")
    battle.enemy_hand = []
    battle.hand = [{"id": "player-heavy", "key": "heavy_strike"}]
    before = battle.enemy.hp

    assert battle.play_card("player-heavy").ok is True

    assert battle.enemy.hp == before - 10
    assert battle.participant(Side.PLAYER).weapon_used_this_turn is False


def test_the_weapon_bonus_comes_back_when_its_owner_starts_a_new_turn():
    battle = wear_gear(make_battle(), Side.PLAYER, "longsword")
    battle.enemy_hand = []
    battle.hand = [{"id": "player-slash", "key": "slash"}]
    battle.play_card("player-slash")
    assert battle.participant(Side.PLAYER).weapon_used_this_turn is True

    battle.start_turn(Side.PLAYER)

    assert battle.participant(Side.PLAYER).weapon_used_this_turn is False


def test_dodging_still_spends_the_weapon_bonus():
    battle = wear_gear(make_battle(), Side.PLAYER, "longsword")
    battle.ai_difficulty = AIDifficulty.HARD
    battle.enemy.energy = 1
    battle.enemy_hand = [{"id": "enemy-dodge", "key": "dodge"}]
    battle.hand = [{"id": "player-slash", "key": "slash"}]
    before = battle.enemy.hp

    assert battle.play_card("player-slash").ok is True

    assert battle.phase is BattlePhase.PLAYER_TURN
    assert battle.enemy.hp == before
    assert battle.participant(Side.PLAYER).weapon_used_this_turn is True


def test_a_boosted_attack_shows_and_deals_the_boosted_damage():
    battle = wear_gear(make_battle(), Side.ENEMY, "longsword")
    battle.hand = [{"id": "player-dodge", "key": "dodge"}]
    battle.end_player_turn()
    withhold_enemy_skill(battle)
    freeze_enemy_piles(battle)
    battle.enemy_hand = [{"id": "enemy-slash", "key": "slash"}]
    before = battle.player.hp

    assert battle.play_card_for(Side.ENEMY, "enemy-slash").ok is True
    assert battle.phase is BattlePhase.RESPONSE
    # 响应窗口里看到的数字，必须是响应之后真正挨到的数字。
    assert battle.pending_attack.damage == 8

    battle.respond("pass")

    assert battle.player.hp == before - 8
    assert any("对你造成 8 点伤害" in entry for entry in battle.log)


def test_the_armor_soaks_the_first_hit_its_owner_takes():
    battle = wear_gear(make_battle(), Side.PLAYER, "iron_armor")
    battle.hand = []
    battle.end_player_turn()
    battle.enemy_hand = [{"id": "enemy-slash", "key": "slash"}]

    battle.play_card_for(Side.ENEMY, "enemy-slash")

    assert battle.player.hp == 32 - 4
    assert battle.participant(Side.PLAYER).armor_used_this_turn is True


def test_the_armor_soaks_only_the_first_hit_of_its_owners_turn():
    battle = wear_gear(make_battle(), Side.PLAYER, "iron_armor")
    battle.hand = []
    battle.end_player_turn()
    battle.enemy_hand = [
        {"id": "enemy-slash", "key": "slash"},
        {"id": "enemy-slash-2", "key": "slash"},
    ]

    battle.play_card_for(Side.ENEMY, "enemy-slash")
    battle.play_card_for(Side.ENEMY, "enemy-slash-2")

    assert battle.player.hp == 32 - 4 - 6


def test_the_armor_comes_back_when_its_owner_starts_a_new_turn():
    battle = wear_gear(make_battle(), Side.PLAYER, "iron_armor")
    battle.hand = []
    battle.end_player_turn()
    battle.enemy_hand = [{"id": "enemy-slash", "key": "slash"}]
    battle.play_card_for(Side.ENEMY, "enemy-slash")
    assert battle.participant(Side.PLAYER).armor_used_this_turn is True

    battle.start_turn(Side.PLAYER)

    assert battle.participant(Side.PLAYER).armor_used_this_turn is False


def test_the_armor_also_soaks_hero_skill_damage():
    battle = pin_enemy_hero(make_battle("warrior"), "mage")
    wear_gear(battle, Side.PLAYER, "iron_armor")
    battle.hand = []
    freeze_enemy_piles(battle)
    battle.end_player_turn()

    assert battle.use_skill_for(Side.ENEMY).ok is True

    assert battle.player.hp == 32 - 8
    assert battle.participant(Side.PLAYER).armor_used_this_turn is True


def test_the_armor_reduces_damage_before_the_shield_absorbs_it():
    battle = wear_gear(make_battle(), Side.PLAYER, "iron_armor")
    battle.player.shield = 5
    battle.hand = []
    battle.end_player_turn()
    battle.enemy_hand = [{"id": "enemy-slash", "key": "slash"}]

    battle.play_card_for(Side.ENEMY, "enemy-slash")

    # 先减 2 再进护盾：5 点护盾只吸收 4 点，剩下的 1 点还留在身上。
    assert battle.player.shield == 1
    assert battle.player.hp == 32


def test_the_armor_is_spent_even_when_the_hit_takes_no_health():
    battle = wear_gear(make_battle(), Side.PLAYER, "iron_armor")
    battle.player.shield = 10
    battle.hand = []
    battle.end_player_turn()
    battle.enemy_hand = [{"id": "enemy-slash", "key": "slash"}]

    battle.play_card_for(Side.ENEMY, "enemy-slash")

    assert battle.player.hp == 32
    assert battle.player.shield == 6
    assert battle.participant(Side.PLAYER).armor_used_this_turn is True


def test_dodging_an_attack_does_not_spend_the_armor():
    battle = wear_gear(make_battle(), Side.PLAYER, "iron_armor")
    battle.hand = [{"id": "player-dodge", "key": "dodge"}]
    battle.end_player_turn()
    withhold_enemy_skill(battle)
    battle.enemy_hand = [{"id": "enemy-slash", "key": "slash"}]
    battle.play_card_for(Side.ENEMY, "enemy-slash")
    assert battle.phase is BattlePhase.RESPONSE

    assert battle.respond("dodge").ok is True

    assert battle.player.hp == 32
    assert battle.participant(Side.PLAYER).armor_used_this_turn is False


def assert_consistent(battle):
    """响应窗口只在有待响应攻击时存在；能量不为负；双方四个牌区守恒。"""
    pending = battle.pending_attack
    in_response = battle.phase is BattlePhase.RESPONSE
    assert in_response == (pending is not None), battle.phase
    if pending is not None:
        assert pending.defender is not pending.attacker
    for side in (Side.PLAYER, Side.ENEMY):
        participant = battle.participant(side)
        assert participant.combatant.energy >= 0, (side, participant.combatant)
        equipped = [
            slot.key
            for slot in (participant.weapon, participant.armor)
            if slot is not None
        ]
        keys = (
            Counter(card["key"] for card in participant.hand)
            + Counter(participant.draw_pile)
            + Counter(participant.discard_pile)
            + Counter(equipped)
        )
        # 攻击挂起时那张牌已经在弃牌区，装备则在槽里，任何时刻都应当正好是整副牌。
        assert keys == Counter(FIXED_DECK_KEYS), (side, keys)


def test_random_play_stays_consistent_through_both_sides_responses():
    """随机对局覆盖双方闪避 / 放弃的递归续跑，守住不变量而不是某条固定路径。"""
    rng = random.Random(20260920)
    for _ in range(60):
        battle = BattleState.create(
            rng.choice(["warrior", "mage", "ranger"]),
            rng,
            rng.choice(list(AIDifficulty)),
        )
        assert_consistent(battle)
        for _ in range(120):
            if battle.is_finished():
                break
            if battle.phase is BattlePhase.RESPONSE:
                battle.respond("dodge" if rng.random() < 0.5 else "pass")
            else:
                side = battle.current_side()
                affordable = [
                    card
                    for card in battle.participant(side).hand
                    if CARDS[card["key"]].effect_type != "dodge"
                    and CARDS[card["key"]].cost
                    <= battle.participant(side).combatant.energy
                ]
                if affordable and rng.random() < 0.7:
                    battle.play_card_for(side, rng.choice(affordable)["id"])
                elif rng.random() < 0.5:
                    battle.use_skill_for(side)
                else:
                    battle.end_turn_for(side)
            assert_consistent(battle)


# --- Task 5: AI 信息边界 ---


def test_enemy_observation_describes_the_enemy_as_self_and_hides_the_player_deck():
    battle = make_battle()
    battle.enemy.shield = 5
    battle.player.energy = 2

    observation = battle.enemy_observation()

    assert observation.self_state.hero_key == battle.enemy_hero.key
    assert observation.self_state.shield == 5
    assert observation.opponent_state.hero_key == battle.hero.key
    assert observation.opponent_state.energy == 2
    assert observation.own_hand == tuple(battle.enemy_hand)
    # 公共弃牌区是明牌，对手手牌与抽牌堆不是——观察视图里根本没有它们的容身之处。
    assert observation.public_discard_keys == tuple(battle.discard_pile)
    assert not hasattr(observation.opponent_state, "hand")
    assert not hasattr(observation.opponent_state, "draw_pile")


def test_enemy_observation_carries_the_pending_attack():
    battle = make_battle()
    # 打出的攻击牌是明牌，伤害值也是公开的，所以它属于观察视图。
    battle.pending_attack = PendingAttack(
        attacker=Side.PLAYER,
        defender=Side.ENEMY,
        card_key="heavy_strike",
        card_name="重击",
        damage=10,
    )

    assert battle.enemy_observation().pending_attack == battle.pending_attack
