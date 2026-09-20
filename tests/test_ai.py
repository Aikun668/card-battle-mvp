import random
from dataclasses import fields

from game.ai import (
    AIObservation,
    PublicParticipantState,
    choose_enemy_response,
    estimate_player_threat,
    get_available_enemy_actions,
    rank_enemy_actions,
    rank_enemy_responses,
    score_dodge,
    select_enemy_action,
)
from game.battle import BattleState
from game.catalog import CARDS, CATALOG_KEYS, FIXED_DECK_KEYS, HEROES
from game.models import AIDifficulty, BattlePhase, PendingAttack, Side


def withhold_enemy_skill(battle):
    """把测试隔离在普通牌上：技能标记为已用，本回合不再进入候选。"""
    battle.participant(Side.ENEMY).skill_used_this_turn = True
    return battle


def make_battle():
    # 电脑也有英雄技能了，下面这些用例考的是普通牌评分，先把技能隔离掉。
    return withhold_enemy_skill(
        BattleState.create("warrior", random.Random(3), starting_side=Side.PLAYER)
    )


def battle_with_enemy_hero(hero_key):
    """电脑英雄固定下来，专门测试英雄技能的行为。"""
    battle = BattleState.create("warrior", random.Random(3), starting_side=Side.PLAYER)
    battle.participants[Side.ENEMY].hero = HEROES[hero_key]
    return battle


def battle_with_three_ranked_choices():
    battle = make_battle()
    battle.enemy.hp = battle.enemy.max_hp
    battle.player.hp = battle.player.max_hp
    battle.enemy.energy = 3
    battle.enemy_hand = [
        {"id": "best", "key": "fireball"},
        {"id": "second", "key": "heavy_strike"},
        {"id": "third", "key": "slash"},
    ]
    return battle


def log_index(battle, text):
    return next(i for i, entry in enumerate(battle.log) if text in entry)


# --- Task 3: difficulty selection ---


def test_hard_always_selects_the_top_scored_action():
    battle = battle_with_three_ranked_choices()
    top = rank_enemy_actions(battle.enemy_observation(), AIDifficulty.HARD)[0]
    for seed in range(5):
        selected = select_enemy_action(
            battle.enemy_observation(), AIDifficulty.HARD, random.Random(seed)
        )
        assert selected.card_id == top.card_id


def _pick_rates(difficulty, runs=400):
    picks = [
        select_enemy_action(
            battle_with_three_ranked_choices().enemy_observation(),
            difficulty,
            random.Random(seed),
        ).card_id
        for seed in range(runs)
    ]
    return picks.count("best") / runs


def test_medium_mostly_selects_the_top_action_but_sometimes_the_second():
    battle = battle_with_three_ranked_choices()
    picks = [
        select_enemy_action(
            battle.enemy_observation(), AIDifficulty.MEDIUM, random.Random(seed)
        ).card_id
        for seed in range(400)
    ]
    assert set(picks) == {"best", "second"}
    assert picks.count("best") / len(picks) >= 0.8


def test_easy_selects_worse_than_medium_and_hard():
    easy = _pick_rates(AIDifficulty.EASY)
    medium = _pick_rates(AIDifficulty.MEDIUM)
    hard = _pick_rates(AIDifficulty.HARD)
    assert easy < medium < hard == 1.0


def test_easy_can_select_a_non_top_action():
    battle = battle_with_three_ranked_choices()
    seen = {
        select_enemy_action(
            battle.enemy_observation(), AIDifficulty.EASY, random.Random(seed)
        ).card_id
        for seed in range(30)
    }
    assert seen - {"best"}, "简单难度必须真的会选中非最优选项"


def test_selection_is_reproducible_for_the_same_seed():
    battle = battle_with_three_ranked_choices()
    first = select_enemy_action(
        battle.enemy_observation(), AIDifficulty.EASY, random.Random(11)
    )
    second = select_enemy_action(
        battle.enemy_observation(), AIDifficulty.EASY, random.Random(11)
    )
    assert first == second


def test_every_difficulty_selects_the_only_candidate():
    battle = make_battle()
    battle.enemy_hand = []
    for difficulty in AIDifficulty:
        selected = select_enemy_action(
            battle.enemy_observation(), difficulty, random.Random(2)
        )
        assert selected.kind == "pass"


def test_easy_never_picks_an_action_with_no_upside():
    battle = make_battle()
    battle.enemy.hp = battle.enemy.max_hp
    battle.enemy_hand = [{"id": "useless-heal", "key": "heal"}]
    for seed in range(30):
        selected = select_enemy_action(
            battle.enemy_observation(), AIDifficulty.EASY, random.Random(seed)
        )
        assert selected.kind == "pass"


def test_hard_lookahead_flips_to_defence_when_the_player_can_kill_next_turn():
    battle = make_battle()
    # 固定生命上限，"半血恐惧"的评分才不会随本局随机到的电脑英雄漂移。
    battle.enemy.max_hp = 28
    battle.enemy.hp = 14
    battle.enemy.shield = 0
    battle.enemy.energy = 3
    battle.player.hp = battle.player.max_hp
    battle.hand = [{"id": "p-fireball", "key": "fireball"}]
    battle.enemy_hand = [
        {"id": "fireball", "key": "fireball"},
        {"id": "shield", "key": "shield"},
    ]
    medium_top = rank_enemy_actions(battle.enemy_observation(), AIDifficulty.MEDIUM)[0]
    hard_top = rank_enemy_actions(battle.enemy_observation(), AIDifficulty.HARD)[0]
    assert medium_top.card_id == "fireball"
    assert hard_top.card_id == "shield"


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
    ranked = rank_enemy_actions(battle.enemy_observation(), AIDifficulty.HARD)
    assert ranked[0].card_id == "heavy"


def test_heal_near_max_health_scores_below_damage():
    battle = make_battle()
    battle.enemy.hp = battle.enemy.max_hp - 1
    battle.enemy_hand = [
        {"id": "heal", "key": "heal"},
        {"id": "slash", "key": "slash"},
    ]
    ranked = rank_enemy_actions(battle.enemy_observation(), AIDifficulty.MEDIUM)
    assert ranked[0].card_id == "slash"


def test_existing_shield_makes_further_shield_score_below_attack():
    battle = make_battle()
    battle.enemy.hp = battle.enemy.max_hp
    battle.enemy.shield = 12
    battle.enemy_hand = [
        {"id": "shield", "key": "shield"},
        {"id": "slash", "key": "slash"},
    ]
    ranked = rank_enemy_actions(battle.enemy_observation(), AIDifficulty.MEDIUM)
    assert ranked[0].card_id == "slash"


def test_actual_healing_outranks_plain_attack_when_hurt_and_no_kill_exists():
    battle = make_battle()
    battle.enemy.hp = 10
    battle.player.hp = battle.player.max_hp
    battle.enemy_hand = [
        {"id": "heal", "key": "heal"},
        {"id": "slash", "key": "slash"},
    ]
    ranked = rank_enemy_actions(battle.enemy_observation(), AIDifficulty.MEDIUM)
    assert ranked[0].card_id == "heal"


def test_attack_that_punches_through_shield_beats_a_fully_absorbed_one():
    battle = make_battle()
    battle.enemy.hp = battle.enemy.max_hp
    battle.player.hp = battle.player.max_hp
    battle.player.shield = 6
    battle.enemy.energy = 3
    battle.enemy_hand = [
        {"id": "slash", "key": "slash"},
        {"id": "heavy", "key": "heavy_strike"},
    ]
    ranked = rank_enemy_actions(battle.enemy_observation(), AIDifficulty.MEDIUM)
    assert ranked[0].card_id == "heavy"


def test_enemy_keeps_attacking_a_heavily_shielded_player_instead_of_stalling():
    battle = make_battle()
    battle.enemy.hp = battle.enemy.max_hp
    battle.player.hp = battle.player.max_hp
    battle.player.shield = 12
    battle.enemy.energy = 3
    battle.enemy_hand = [
        {"id": "enemy-fireball", "key": "fireball"},
        {"id": "enemy-shield", "key": "shield"},
    ]
    ranked = rank_enemy_actions(battle.enemy_observation(), AIDifficulty.MEDIUM)
    assert ranked[0].card_id == "enemy-fireball"


def test_a_dying_enemy_defends_instead_of_trading_damage():
    battle = make_battle()
    battle.enemy.hp = 6
    battle.player.hp = battle.player.max_hp
    battle.enemy_hand = [
        {"id": "fireball", "key": "fireball"},
        {"id": "heal", "key": "heal"},
    ]
    ranked = rank_enemy_actions(battle.enemy_observation(), AIDifficulty.MEDIUM)
    assert ranked[0].card_id == "heal"


def test_pass_ranks_last_when_a_useful_action_exists():
    battle = make_battle()
    battle.enemy_hand = [{"id": "slash", "key": "slash"}]
    ranked = rank_enemy_actions(battle.enemy_observation(), AIDifficulty.MEDIUM)
    assert ranked[-1].kind == "pass"


def test_pass_outranks_a_heal_that_would_restore_nothing():
    battle = make_battle()
    battle.enemy.hp = battle.enemy.max_hp
    battle.enemy_hand = [{"id": "heal", "key": "heal"}]
    ranked = rank_enemy_actions(battle.enemy_observation(), AIDifficulty.MEDIUM)
    assert ranked[0].kind == "pass"


def test_selection_does_not_mutate_the_battle():
    battle = battle_with_three_ranked_choices()
    before = battle.to_dict()
    select_enemy_action(battle.enemy_observation(), AIDifficulty.EASY, random.Random(1))
    assert battle.to_dict() == before


def test_ranking_does_not_mutate_the_battle():
    battle = make_battle()
    battle.enemy_hand = [{"id": "slash", "key": "slash"}]
    before = battle.to_dict()
    rank_enemy_actions(battle.enemy_observation(), AIDifficulty.MEDIUM)
    assert battle.to_dict() == before


def test_available_enemy_actions_include_affordable_cards_and_pass():
    battle = make_battle()
    battle.enemy_hand = [{"id": "enemy-slash", "key": "slash"}]
    actions = get_available_enemy_actions(battle.enemy_observation())
    assert {action.kind for action in actions} == {"card", "pass"}
    assert any(action.card_id == "enemy-slash" for action in actions)


def test_unaffordable_cards_are_not_candidates():
    battle = make_battle()
    battle.enemy.energy = 1
    battle.enemy_hand = [{"id": "enemy-fireball", "key": "fireball"}]
    actions = get_available_enemy_actions(battle.enemy_observation())
    assert all(action.kind != "card" for action in actions)


def test_dodge_is_never_an_enemy_candidate():
    battle = make_battle()
    battle.enemy_hand = [{"id": "enemy-dodge", "key": "dodge"}]
    actions = get_available_enemy_actions(battle.enemy_observation())
    assert all(action.kind != "card" for action in actions)


def test_pass_is_available_even_with_an_empty_hand():
    battle = make_battle()
    battle.enemy_hand = []
    actions = get_available_enemy_actions(battle.enemy_observation())
    assert [action.kind for action in actions] == ["pass"]


def test_candidate_generation_does_not_mutate_the_battle():
    battle = make_battle()
    battle.enemy_hand = [{"id": "enemy-slash", "key": "slash"}]
    before = battle.to_dict()
    get_available_enemy_actions(battle.enemy_observation())
    assert battle.to_dict() == before


def test_enemy_heals_when_badly_hurt():
    battle = make_battle()
    battle.enemy.hp = 8
    battle.enemy_hand = [
        {"id": "enemy-heal", "key": "heal"},
        {"id": "enemy-slash", "key": "slash"},
    ]
    ranked = rank_enemy_actions(battle.enemy_observation(), AIDifficulty.HARD)
    assert ranked[0].card_id == "enemy-heal"


def test_enemy_goes_for_lethal_damage_when_the_player_is_low():
    battle = make_battle()
    battle.player.hp = 10
    battle.enemy_hand = [
        {"id": "enemy-slash", "key": "slash"},
        {"id": "enemy-fireball", "key": "fireball"},
    ]
    ranked = rank_enemy_actions(battle.enemy_observation(), AIDifficulty.HARD)
    assert ranked[0].card_id == "enemy-fireball"


def test_enemy_shields_when_hurt_and_no_heal_is_available():
    battle = make_battle()
    battle.enemy.hp = 14
    battle.player.hp = 24
    battle.enemy_hand = [
        {"id": "enemy-shield", "key": "shield"},
        {"id": "enemy-slash", "key": "slash"},
    ]
    ranked = rank_enemy_actions(battle.enemy_observation(), AIDifficulty.HARD)
    assert ranked[0].card_id == "enemy-shield"


def test_enemy_passes_when_it_cannot_afford_any_card():
    battle = make_battle()
    battle.enemy.energy = 0
    battle.enemy_hand = [
        {"id": "enemy-slash", "key": "slash"},
        {"id": "enemy-fireball", "key": "fireball"},
    ]
    for difficulty in AIDifficulty:
        assert (
            select_enemy_action(
                battle.enemy_observation(), difficulty, random.Random(5)
            ).kind
            == "pass"
        )


# --- Task 4: enemy turn loop ---


def test_enemy_re_ranks_actions_after_each_play():
    battle = make_battle()
    battle.ai_difficulty = AIDifficulty.HARD
    battle.end_player_turn()
    withhold_enemy_skill(battle)
    battle.enemy_hand = [
        {"id": "enemy-heavy", "key": "heavy_strike"},
        {"id": "enemy-slash", "key": "slash"},
    ]
    battle.resolve_enemy_turn()
    # 重击花掉 2 点能量，剩余 1 点只够斩击：第二次选择必须重新读取扣费后的状态。
    assert log_index(battle, "电脑使用【重击】") < log_index(battle, "电脑使用【斩击】")
    assert battle.enemy.energy == 0
    assert battle.player.hp == 32 - 10 - 6


def test_enemy_stops_playing_once_energy_runs_out():
    battle = make_battle()
    battle.ai_difficulty = AIDifficulty.HARD
    battle.end_player_turn()
    withhold_enemy_skill(battle)
    battle.enemy_hand = [
        {"id": "enemy-fireball", "key": "fireball"},
        {"id": "enemy-slash", "key": "slash"},
    ]
    battle.resolve_enemy_turn()
    assert battle.player.hp == 32 - 14
    assert all("斩击" not in entry for entry in battle.log)


def test_enemy_stops_playing_the_moment_the_player_dies():
    battle = make_battle()
    battle.ai_difficulty = AIDifficulty.HARD
    battle.hand = []
    battle.player.hp = 6
    battle.end_player_turn()
    withhold_enemy_skill(battle)
    battle.enemy_hand = [
        {"id": "enemy-heavy", "key": "heavy_strike"},
        {"id": "enemy-slash", "key": "slash"},
    ]
    battle.resolve_enemy_turn()
    assert battle.phase is BattlePhase.DEFEAT
    assert battle.player.hp == 0
    assert battle.round_number == 1
    # 6 点生命时斩击就能击杀，比 10 点伤害的重击更省能量，所以只出一张牌。
    assert battle.log[-1] == "电脑使用【斩击】，对你造成 6 点伤害"
    assert sum(1 for entry in battle.log if entry.startswith("电脑使用")) == 1


def test_enemy_energy_starts_fresh_every_enemy_turn():
    battle = make_battle()
    battle.ai_difficulty = AIDifficulty.HARD
    battle.enemy.energy = 0
    battle.end_player_turn()
    withhold_enemy_skill(battle)
    battle.enemy_hand = [{"id": "enemy-slash", "key": "slash"}]
    battle.resolve_enemy_turn()
    assert battle.player.hp == 32 - 6


def test_enemy_deck_is_the_same_fixed_deck_as_the_player():
    battle = make_battle()
    enemy_keys = (
        [card["key"] for card in battle.enemy_hand]
        + list(battle.enemy_draw_pile)
        + list(battle.enemy_discard_pile)
    )
    assert sorted(enemy_keys) == sorted(FIXED_DECK_KEYS)


def test_passing_a_response_resumes_the_remaining_enemy_actions():
    battle = make_battle()
    battle.ai_difficulty = AIDifficulty.HARD
    battle.player.energy = 3
    battle.hand = [{"id": "player-dodge", "key": "dodge"}]
    battle.end_player_turn()
    withhold_enemy_skill(battle)
    battle.enemy_hand = [
        {"id": "enemy-heavy", "key": "heavy_strike"},
        {"id": "enemy-slash", "key": "slash"},
    ]
    battle.resolve_enemy_turn()
    assert battle.phase is BattlePhase.RESPONSE
    battle.respond("pass")
    assert battle.player.hp == 32 - 10
    assert battle.phase is BattlePhase.RESPONSE
    assert battle.pending_attack.card_name == "斩击"
    battle.respond("pass")
    assert battle.player.hp == 32 - 16
    assert battle.phase is BattlePhase.PLAYER_TURN
    assert battle.round_number == 2


def test_dodging_one_attack_lets_the_next_one_land():
    battle = make_battle()
    battle.ai_difficulty = AIDifficulty.HARD
    battle.player.energy = 3
    battle.hand = [{"id": "player-dodge", "key": "dodge"}]
    battle.end_player_turn()
    withhold_enemy_skill(battle)
    battle.enemy_hand = [
        {"id": "enemy-heavy", "key": "heavy_strike"},
        {"id": "enemy-slash", "key": "slash"},
    ]
    battle.resolve_enemy_turn()
    battle.respond("dodge")
    # 闪避用掉后手里没有第二张闪避，剩下的斩击直接结算。
    assert battle.player.hp == 32 - 6
    assert battle.phase is BattlePhase.PLAYER_TURN
    assert battle.round_number == 2


def test_end_turn_runs_enemy_actions_until_pass():
    battle = make_battle()
    initial_hp = battle.player.hp
    assert battle.end_player_turn().ok is True
    withhold_enemy_skill(battle)
    battle.enemy_hand = [{"id": "enemy-slash", "key": "slash"}]
    result = battle.resolve_enemy_turn()
    assert result.ok is True
    assert battle.player.hp == initial_hp - 6
    assert battle.phase.value == "PLAYER_TURN"
    assert battle.round_number == 2
    assert battle.player.energy == 3
    assert battle.skill_used_this_turn is False


def test_resolve_enemy_turn_with_no_affordable_card_still_returns_to_player():
    battle = make_battle()
    battle.end_player_turn()
    withhold_enemy_skill(battle)
    battle.enemy_hand = []
    battle.resolve_enemy_turn()
    assert battle.phase.value == "PLAYER_TURN"
    assert battle.player.hp == 32  # undamaged


# --- Task 3: 电脑的英雄技能与战略空过 ---


def test_enemy_hero_skill_is_a_candidate_next_to_its_cards():
    battle = battle_with_enemy_hero("mage")
    battle.enemy_hand = [{"id": "enemy-slash", "key": "slash"}]
    battle.enemy.energy = 3

    kinds = {
        action.kind
        for action in get_available_enemy_actions(battle.enemy_observation())
    }

    assert kinds == {"card", "skill", "pass"}


def test_enemy_skill_leaves_the_candidates_once_used_or_unaffordable():
    battle = battle_with_enemy_hero("mage")
    battle.enemy_hand = []
    assert any(
        action.kind == "skill"
        for action in get_available_enemy_actions(battle.enemy_observation())
    )

    withhold_enemy_skill(battle)
    assert all(
        action.kind != "skill"
        for action in get_available_enemy_actions(battle.enemy_observation())
    )

    battle.participant(Side.ENEMY).skill_used_this_turn = False
    battle.enemy.energy = 1
    assert all(
        action.kind != "skill"
        for action in get_available_enemy_actions(battle.enemy_observation())
    )


def test_skill_scores_exactly_like_an_equivalent_card():
    # 法师技能是 10 点伤害 / 2 能量，与重击同值同费，两者评分必须相同。
    battle = battle_with_enemy_hero("mage")
    battle.enemy_hand = [{"id": "enemy-heavy", "key": "heavy_strike"}]
    battle.enemy.energy = 3
    battle.player.shield = 0

    scores = {
        a.kind: a.score
        for a in rank_enemy_actions(battle.enemy_observation(), AIDifficulty.MEDIUM)
    }

    assert scores["skill"] == scores["card"]


def test_medium_and_hard_pass_to_keep_the_last_energy_for_a_dodge():
    for difficulty in (AIDifficulty.MEDIUM, AIDifficulty.HARD):
        battle = battle_that_could_waste_its_dodge_energy()
        ranked = rank_enemy_actions(battle.enemy_observation(), difficulty)
        assert ranked[0].kind == "pass", difficulty
        assert (
            select_enemy_action(
                battle.enemy_observation(), difficulty, random.Random(0)
            ).kind
            == "pass"
        )


def test_easy_spends_the_last_energy_instead_of_holding_it():
    battle = battle_that_could_waste_its_dodge_energy()

    ranked = rank_enemy_actions(battle.enemy_observation(), AIDifficulty.EASY)

    assert ranked[0].card_id == "enemy-slash"


def battle_that_could_waste_its_dodge_energy():
    """手里有闪避、能量只剩 1 点，唯一的普通牌打在厚护盾上几乎没收益。"""
    battle = make_battle()
    battle.hand = []
    battle.enemy.energy = 1
    battle.player.shield = 12
    battle.enemy_hand = [
        {"id": "enemy-dodge", "key": "dodge"},
        {"id": "enemy-slash", "key": "slash"},
    ]
    return battle


# --- Task 4: 电脑作为防御方的闪避评分 ---


def battle_with_a_pending_attack(damage: int):
    """把电脑摆进响应窗口：玩家打出一张伤害牌，电脑手里有闪避和 1 点能量。"""
    battle = make_battle()
    battle.pending_attack = PendingAttack(
        attacker=Side.PLAYER,
        defender=Side.ENEMY,
        card_key="heavy_strike",
        card_name="重击",
        damage=damage,
    )
    battle.enemy.energy = 1
    battle.enemy_hand = [{"id": "enemy-dodge", "key": "dodge"}]
    return battle


def test_dodge_scores_only_the_damage_that_would_reach_health():
    battle = battle_with_a_pending_attack(10)
    battle.enemy.shield = 4

    # 护盾先吸掉 4 点，闪避真正救下的只有 6 点生命。
    assert score_dodge(battle.enemy_observation()) == 6.0


def test_dodge_scores_nothing_when_the_shield_absorbs_the_whole_hit():
    battle = battle_with_a_pending_attack(10)
    battle.enemy.shield = 12

    assert score_dodge(battle.enemy_observation()) == 0.0
    assert (
        rank_enemy_responses(battle.enemy_observation(), AIDifficulty.HARD)[0].kind
        == "pass"
    )


def test_no_difficulty_spends_a_dodge_that_saves_no_health():
    """零收益的闪避不参与抽取：难度权重可以选得差，但不该白扔一张牌。"""
    battle = battle_with_a_pending_attack(10)
    battle.enemy.shield = 12

    for difficulty in AIDifficulty:
        kinds = {
            choose_enemy_response(
                battle.enemy_observation(), difficulty, random.Random(seed)
            ).kind
            for seed in range(30)
        }
        assert kinds == {"pass"}, difficulty


def test_hard_gives_up_a_small_hit_to_keep_its_last_energy_for_a_bigger_one():
    """只剩 1 点能量时，闪避就等于放弃本回合后面所有闪避机会。"""
    battle = battle_with_a_pending_attack(2)

    kinds = {
        choose_enemy_response(
            battle.enemy_observation(), AIDifficulty.HARD, random.Random(seed)
        ).kind
        for seed in range(30)
    }

    assert kinds == {"pass"}


def test_hard_never_declines_a_dodge_that_saves_real_health():
    battle = battle_with_a_pending_attack(10)

    kinds = {
        choose_enemy_response(
            battle.enemy_observation(), AIDifficulty.HARD, random.Random(seed)
        ).kind
        for seed in range(20)
    }

    assert kinds == {"dodge"}


def test_easy_occasionally_declines_a_dodge_the_higher_levels_take():
    battle = battle_with_a_pending_attack(10)
    rng = random.Random(3)

    easy = [
        choose_enemy_response(battle.enemy_observation(), AIDifficulty.EASY, rng).kind
        for _ in range(200)
    ]
    medium = [
        choose_enemy_response(battle.enemy_observation(), AIDifficulty.MEDIUM, rng).kind
        for _ in range(200)
    ]

    # 简单难度允许看走眼，但不能变成每次都放弃；难度越高越倾向于闪避。
    assert 0 < easy.count("pass") < 200
    assert easy.count("dodge") < medium.count("dodge")


def test_response_candidates_are_only_dodge_and_pass():
    battle = battle_with_a_pending_attack(10)

    kinds = [
        candidate.kind
        for candidate in rank_enemy_responses(
            battle.enemy_observation(), AIDifficulty.EASY
        )
    ]

    assert sorted(kinds) == ["dodge", "pass"]


def test_responding_does_not_peek_at_or_change_the_enemy_hand():
    battle = battle_with_a_pending_attack(10)
    before = battle.to_dict()

    choose_enemy_response(
        battle.enemy_observation(), AIDifficulty.HARD, random.Random(0)
    )

    assert battle.to_dict() == before


# --- Task 5: 信息边界 ---


def battle_with_a_dangerous_enemy():
    """电脑半血、手里有火球和护盾，困难模式正处在"要不要自保"的分岔上。"""
    battle = make_battle()
    battle.enemy.max_hp = 28
    battle.enemy.hp = 12
    battle.enemy.shield = 0
    battle.enemy.energy = 3
    battle.player.hp = battle.player.max_hp
    battle.enemy_hand = [
        {"id": "enemy-fireball", "key": "fireball"},
        {"id": "enemy-shield", "key": "shield"},
    ]
    return battle


def fireball_score(battle, difficulty=AIDifficulty.MEDIUM):
    return next(
        candidate.score
        for candidate in rank_enemy_actions(battle.enemy_observation(), difficulty)
        if candidate.card_id == "enemy-fireball"
    )


def test_the_observation_is_unchanged_when_only_the_player_hand_changes():
    battle = battle_with_a_dangerous_enemy()
    before = battle.enemy_observation()

    battle.hand = [{"id": "hidden-fireball", "key": "fireball"}]

    assert battle.enemy_observation() == before


def test_hard_ai_rank_is_unchanged_when_only_the_hidden_player_hand_changes():
    battle = battle_with_a_dangerous_enemy()
    first = rank_enemy_actions(battle.enemy_observation(), AIDifficulty.HARD)

    battle.hand = [{"id": "hidden-fireball", "key": "fireball"}]

    assert rank_enemy_actions(battle.enemy_observation(), AIDifficulty.HARD) == first


def test_player_public_state_moves_the_scores_the_hidden_hand_does_not():
    battle = battle_with_a_dangerous_enemy()
    before = fireball_score(battle)

    battle.hand = [{"id": "hidden-heal", "key": "heal"}]
    assert fireball_score(battle) == before

    battle.player.shield = 20
    assert fireball_score(battle) < before


def test_the_observation_carries_the_board_and_its_own_hand():
    battle = battle_with_a_dangerous_enemy()
    battle.discard_pile = ["slash", "dodge"]

    observation = battle.enemy_observation()

    assert observation.own_hand == tuple(battle.enemy_hand)
    assert observation.public_discard_keys == ("slash", "dodge")
    assert observation.catalog_keys == CATALOG_KEYS
    assert observation.self_state.hero_key == battle.enemy_hero.key
    assert (observation.self_state.hp, observation.self_state.shield) == (
        battle.enemy.hp,
        battle.enemy.shield,
    )
    assert observation.self_state.energy == battle.enemy.energy
    assert observation.opponent_state.hero_key == battle.hero.key
    assert observation.opponent_state.max_hp == battle.player.max_hp


def test_the_observation_is_a_snapshot_not_a_live_view_of_the_battle():
    battle = battle_with_a_dangerous_enemy()
    observation = battle.enemy_observation()

    battle.enemy_hand.clear()
    battle.enemy.shield = 9

    assert len(observation.own_hand) == 2
    assert observation.self_state.shield == 0


def test_the_observation_types_have_nowhere_to_put_the_opponent_hand_or_deck():
    """边界靠类型本身守住：这两个 dataclass 里没有能装隐藏信息的字段。"""
    assert {field.name for field in fields(PublicParticipantState)} == {
        "hero_key",
        "max_hp",
        "hp",
        "shield",
        "energy",
        "skill_used_this_turn",
    }
    assert {field.name for field in fields(AIObservation)} == {
        "self_state",
        "opponent_state",
        "own_hand",
        "public_discard_keys",
        "catalog_keys",
        "pending_attack",
    }


def test_threat_estimate_ignores_the_hidden_hand_and_uses_the_public_table():
    battle = battle_with_a_dangerous_enemy()

    battle.hand = []
    without_any_card = estimate_player_threat(battle.enemy_observation())
    battle.hand = [{"id": "hidden-slash", "key": "slash"}]
    with_a_hidden_slash = estimate_player_threat(battle.enemy_observation())

    # 玩家手里有什么不影响估算；公开牌表里买得起的最强伤害牌才是上界。
    assert without_any_card == with_a_hidden_slash == CARDS["fireball"].value


def test_threat_estimate_never_drops_below_the_public_table_maximum():
    """技能也要算进去（法师火球术 10、游侠连射 6），只是当前都被火球 14 压过。"""
    battle = battle_with_a_dangerous_enemy()
    battle.participants[Side.PLAYER].hero = HEROES["mage"]

    assert estimate_player_threat(battle.enemy_observation()) == CARDS["fireball"].value
