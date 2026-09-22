import random
from dataclasses import fields

from game.ai import (
    ActionCandidate,
    AIObservation,
    PublicParticipantState,
    _after_action,
    _tactical_score,
    choose_enemy_response,
    estimate_player_threat,
    get_available_enemy_actions,
    rank_enemy_actions,
    rank_enemy_responses,
    score_dodge,
    select_enemy_action,
)
from game.battle import BattleState
from game.catalog import CARDS, CATALOG_KEYS, HERO_DECKS, HEROES
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


def _top_pick_rates(difficulty, runs=400):
    """该难度下选中"本难度排序第一名"的比例；第一名按评分动态取。"""
    hits = 0
    for seed in range(runs):
        battle = battle_with_three_ranked_choices()
        observation = battle.enemy_observation()
        top_id = rank_enemy_actions(observation, difficulty)[0].card_id
        picked = select_enemy_action(
            observation, difficulty, random.Random(seed)
        ).card_id
        if picked == top_id:
            hits += 1
    return hits / runs


def test_medium_mostly_selects_the_top_action_but_sometimes_the_second():
    battle = battle_with_three_ranked_choices()
    ranked = rank_enemy_actions(battle.enemy_observation(), AIDifficulty.MEDIUM)
    top_two = {candidate.card_id for candidate in ranked[:2]}
    picks = [
        select_enemy_action(
            battle.enemy_observation(), AIDifficulty.MEDIUM, random.Random(seed)
        ).card_id
        for seed in range(400)
    ]
    assert set(picks) == top_two
    assert picks.count(ranked[0].card_id) / len(picks) >= 0.8


def test_easy_selects_worse_than_medium_and_hard():
    easy = _top_pick_rates(AIDifficulty.EASY)
    medium = _top_pick_rates(AIDifficulty.MEDIUM)
    hard = _top_pick_rates(AIDifficulty.HARD)
    assert easy < medium < hard == 1.0


def test_easy_can_select_a_non_top_action():
    battle = battle_with_three_ranked_choices()
    top_id = rank_enemy_actions(battle.enemy_observation(), AIDifficulty.EASY)[
        0
    ].card_id
    seen = {
        select_enemy_action(
            battle.enemy_observation(), AIDifficulty.EASY, random.Random(seed)
        ).card_id
        for seed in range(30)
    }
    assert seen - {top_id}, "简单难度必须真的会选中非最优选项"


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
    # 能量只够出一张：两张牌凑不出连招，评分差异就是选择差异。
    battle.enemy.energy = 2
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
    # 6 点生命时重击与斩击都能一击毙命：规划后两条顺序的总分相同，由手牌顺序
    # 裁决，用哪张都合法——关键是击杀成立且只出一张牌。
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


def test_enemy_deck_is_its_own_hero_deck():
    battle = make_battle()
    enemy_keys = (
        [card["key"] for card in battle.enemy_hand]
        + list(battle.enemy_draw_pile)
        + list(battle.enemy_discard_pile)
    )
    assert sorted(enemy_keys) == sorted(HERO_DECKS[battle.enemy_hero.key])


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


def test_dodge_scores_only_what_the_armor_would_let_through():
    battle = battle_with_a_pending_attack(10)
    battle.enemy.shield = 4
    enemy_wearing(battle, "iron_armor")

    # 放弃响应的话，这 10 点会先被铁甲削掉 2 点，剩下的才轮到 4 点护盾。
    assert score_dodge(battle.enemy_observation()) == 4.0


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
        # 装备挂在角色身上，两边都看得见，所以它属于公开状态。
        "weapon_key",
        "armor_key",
        "weapon_used_this_turn",
        "armor_used_this_turn",
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


# --- 装备: AI 决策 ---


def enemy_wearing(battle, card_key):
    """直接给电脑穿上装备：这些用例考的是它的估值，不是打牌流程。"""
    enemy = battle.participant(Side.ENEMY)
    if card_key == "longsword":
        enemy.weapon = CARDS[card_key]
    else:
        enemy.armor = CARDS[card_key]
    return battle


def enemy_scores(battle, difficulty=AIDifficulty.MEDIUM):
    return {
        candidate.card_id: candidate.score
        for candidate in rank_enemy_actions(battle.enemy_observation(), difficulty)
    }


def test_enemy_offers_an_equipment_card_as_a_normal_candidate():
    battle = make_battle()
    battle.enemy_hand = [{"id": "enemy-sword", "key": "longsword"}]

    candidates = get_available_enemy_actions(battle.enemy_observation())

    sword = next(c for c in candidates if c.card_id == "enemy-sword")
    # 装备就是打牌，不新增候选类型：_run_enemy_actions() 一行都不用改。
    assert sword.kind == "card"


def test_weapon_score_counts_the_slashes_left_in_hand():
    battle = make_battle()
    battle.enemy.energy = 1
    battle.enemy_hand = [
        {"id": "enemy-sword", "key": "longsword"},
        {"id": "enemy-slash", "key": "slash"},
    ]

    assert enemy_scores(battle)["enemy-sword"] == CARDS["longsword"].value


def test_weapon_score_is_capped_at_the_one_boost_it_gets_per_turn():
    battle = make_battle()
    battle.enemy.energy = 1
    battle.enemy_hand = [
        {"id": "enemy-sword", "key": "longsword"},
        {"id": "enemy-slash-1", "key": "slash"},
        {"id": "enemy-slash-2", "key": "slash"},
        {"id": "enemy-slash-3", "key": "slash"},
    ]

    # 手里三张斩击，但一回合只加成一次，所以最多按两张计价。
    assert enemy_scores(battle)["enemy-sword"] == 2 * CARDS["longsword"].value


def test_weapon_scores_nothing_when_there_is_no_slash_to_go_with_it():
    battle = make_battle()
    battle.enemy.energy = 1
    battle.enemy_hand = [{"id": "enemy-sword", "key": "longsword"}]

    # 没有斩击时先攒着：装备要花 1 点能量，空穿等于白花。
    assert enemy_scores(battle)["enemy-sword"] == 0.0
    assert (
        rank_enemy_actions(battle.enemy_observation(), AIDifficulty.MEDIUM)[0].kind
        == "pass"
    )


def test_armor_is_worth_more_when_the_enemy_is_hurt():
    def armor_score(battle):
        return enemy_scores(battle)["enemy-armor"]

    healthy = make_battle()
    healthy.enemy.energy = 1
    healthy.enemy_hand = [{"id": "enemy-armor", "key": "iron_armor"}]

    hurt = make_battle()
    hurt.enemy.energy = 1
    hurt.enemy.hp = hurt.enemy.max_hp // 4
    hurt.enemy_hand = [{"id": "enemy-armor", "key": "iron_armor"}]

    assert armor_score(healthy) == CARDS["iron_armor"].value
    assert armor_score(hurt) > armor_score(healthy)


def test_weapon_raises_the_score_of_a_slash_but_not_of_a_fireball():
    def with_hand(battle):
        battle.enemy.energy = 3
        battle.enemy_hand = [
            {"id": "enemy-slash", "key": "slash"},
            {"id": "enemy-fireball", "key": "fireball"},
        ]
        return battle

    bare = enemy_scores(with_hand(make_battle()))
    armed = enemy_scores(with_hand(enemy_wearing(make_battle(), "longsword")))

    # 长剑只强化斩击，火球的评分一点都不该动。
    assert armed["enemy-slash"] > bare["enemy-slash"]
    assert armed["enemy-fireball"] == bare["enemy-fireball"]


def test_a_spent_weapon_no_longer_raises_the_slash_score():
    battle = enemy_wearing(make_battle(), "longsword")
    battle.enemy.energy = 3
    battle.enemy_hand = [{"id": "enemy-slash", "key": "slash"}]
    before = enemy_scores(battle)["enemy-slash"]

    battle.participant(Side.ENEMY).weapon_used_this_turn = True

    assert enemy_scores(battle)["enemy-slash"] < before


def test_a_full_enemy_turn_can_equip_and_then_cash_in_the_bonus():
    battle = make_battle()
    battle.ai_difficulty = AIDifficulty.HARD
    battle.hand = []
    battle.player.shield = 12
    battle.end_player_turn()
    withhold_enemy_skill(battle)
    battle.enemy_hand = [
        {"id": "enemy-sword", "key": "longsword"},
        {"id": "enemy-slash-1", "key": "slash"},
        {"id": "enemy-slash-2", "key": "slash"},
    ]

    battle.resolve_enemy_turn()

    assert battle.participant(Side.ENEMY).weapon.key == "longsword"
    # 先穿剑再出手：8 + 6 = 14 点打穿 12 点护盾，多出的 2 点落在生命上。
    assert battle.player.shield == 0
    assert battle.player.hp == 30


def test_gear_on_either_side_is_public_in_the_observation():
    battle = enemy_wearing(make_battle(), "longsword")
    battle.participant(Side.PLAYER).armor = CARDS["iron_armor"]
    battle.hand = [{"id": "hidden-fireball", "key": "fireball"}]

    observation = battle.enemy_observation()

    assert observation.self_state.weapon_key == "longsword"
    assert observation.self_state.armor_key is None
    assert observation.opponent_state.armor_key == "iron_armor"
    assert observation.opponent_state.weapon_key is None
    # 装备是公开信息，但它不能变成偷看对手手牌的后门。
    assert not hasattr(observation.opponent_state, "hand")


def test_armor_reduces_the_estimated_player_threat():
    battle = make_battle()
    battle.participant(Side.PLAYER).hero = HEROES["mage"]
    without_armor = estimate_player_threat(battle.enemy_observation())

    enemy_wearing(battle, "iron_armor")

    assert without_armor == CARDS["fireball"].value
    assert (
        estimate_player_threat(battle.enemy_observation())
        == without_armor - CARDS["iron_armor"].value
    )


def test_a_spent_armor_does_not_lower_the_threat_estimate():
    battle = enemy_wearing(make_battle(), "iron_armor")
    battle.participant(Side.ENEMY).armor_used_this_turn = True

    assert estimate_player_threat(battle.enemy_observation()) == CARDS["fireball"].value


# --- 伤害连招规划 ---


def battle_with_a_combo_choice():
    """法师电脑：能量 3、技能可用，手里火球 + 斩击。

    火球单独打 14 伤；技能（10）+ 斩击（6）能打 16 伤。
    """
    battle = battle_with_enemy_hero("mage")
    battle.enemy.energy = 3
    battle.player.hp = battle.player.max_hp
    battle.player.shield = 0
    battle.enemy_hand = [
        {"id": "enemy-fireball", "key": "fireball"},
        {"id": "enemy-slash", "key": "slash"},
    ]
    return battle


def test_medium_and_hard_open_with_the_combo_instead_of_the_big_card():
    for difficulty in (AIDifficulty.MEDIUM, AIDifficulty.HARD):
        battle = battle_with_a_combo_choice()
        selected = select_enemy_action(
            battle.enemy_observation(), difficulty, random.Random(0)
        )
        assert selected.card_id != "enemy-fireball", difficulty


def test_a_planned_enemy_turn_deals_the_combo_damage():
    battle = battle_with_a_combo_choice()
    battle.ai_difficulty = AIDifficulty.HARD
    battle.hand = []
    battle.end_player_turn()
    battle.resolve_enemy_turn()

    # 技能 10 + 斩击 6 = 16；逐张贪心只会打火球拿 14。
    assert battle.player.hp == 32 - 16


def test_easy_still_opens_with_the_big_card_without_planning():
    battle = battle_with_a_combo_choice()
    # 简单难度不规划，评分排序维持逐张贪心：火球仍然第一（选择本身带随机性，
    # 这里钉的是排序，不是某一次抽取）。
    ranked = rank_enemy_actions(battle.enemy_observation(), AIDifficulty.EASY)
    assert ranked[0].card_id == "enemy-fireball"


def test_planning_only_lifts_damage_candidates():
    battle = battle_with_enemy_hero("mage")
    battle.enemy.energy = 3
    battle.enemy_hand = [
        {"id": "enemy-shield", "key": "shield"},
        {"id": "enemy-slash", "key": "slash"},
    ]

    def shield_score(difficulty):
        return next(
            candidate.score
            for candidate in rank_enemy_actions(battle.enemy_observation(), difficulty)
            if candidate.card_id == "enemy-shield"
        )

    # 简单难度不规划；防御牌的分数在任何难度下都必须一样。
    assert shield_score(AIDifficulty.HARD) == shield_score(AIDifficulty.EASY)


def test_planning_does_not_delay_a_lethal():
    battle = battle_with_enemy_hero("mage")
    battle.enemy.energy = 3
    battle.player.hp = 8
    battle.player.shield = 0
    battle.enemy_hand = [
        {"id": "enemy-fireball", "key": "fireball"},
        {"id": "enemy-shield", "key": "shield"},
    ]
    ranked = rank_enemy_actions(battle.enemy_observation(), AIDifficulty.HARD)
    # 火球与技能都能击杀 8 血（技能还更省能量），用哪个都行；
    # 关键是击杀手段必须排在看护盾前面。
    assert ranked[0].card_id == "enemy-fireball" or ranked[0].kind == "skill"
    assert ranked[0].card_id != "enemy-shield"


def test_ranking_with_planning_does_not_mutate_the_battle():
    battle = battle_with_a_combo_choice()
    before = battle.to_dict()
    rank_enemy_actions(battle.enemy_observation(), AIDifficulty.HARD)
    assert battle.to_dict() == before


def test_after_action_simulates_a_card_without_touching_the_snapshot():
    battle = battle_with_a_combo_choice()
    observation = battle.enemy_observation()
    candidate = next(
        c
        for c in get_available_enemy_actions(observation)
        if c.card_id == "enemy-fireball"
    )

    after = _after_action(observation, candidate)

    assert (
        after.self_state.energy
        == observation.self_state.energy - CARDS["fireball"].cost
    )
    assert all(card["id"] != "enemy-fireball" for card in after.own_hand)
    # 原快照（以及它背后的对局）一点没动。
    assert observation.self_state.energy == 3
    assert len(observation.own_hand) == 2
    assert observation == battle.enemy_observation()


def test_after_action_marks_the_weapon_bonus_as_spent():
    battle = enemy_wearing(make_battle(), "longsword")
    battle.enemy.energy = 3
    battle.enemy_hand = [{"id": "enemy-slash", "key": "slash"}]
    observation = battle.enemy_observation()
    candidate = next(
        c
        for c in get_available_enemy_actions(observation)
        if c.card_id == "enemy-slash"
    )

    after = _after_action(observation, candidate)

    assert after.self_state.weapon_used_this_turn is True
    assert observation.self_state.weapon_used_this_turn is False


def test_after_action_returns_none_for_pass_or_unaffordable_cards():
    battle = make_battle()
    battle.enemy.energy = 1
    battle.enemy_hand = [{"id": "enemy-fireball", "key": "fireball"}]
    observation = battle.enemy_observation()

    pass_candidate = next(
        c for c in get_available_enemy_actions(observation) if c.kind == "pass"
    )
    unaffordable = ActionCandidate(
        kind="card", card_id="enemy-fireball", card_key="fireball"
    )

    assert _after_action(observation, pass_candidate) is None
    assert _after_action(observation, unaffordable) is None


def test_easy_scores_stay_at_the_tactical_level():
    """简单难度不规划：候选分数就是战术分，一点连招价值都不加。"""
    battle = battle_with_a_combo_choice()
    observation = battle.enemy_observation()

    for candidate in rank_enemy_actions(observation, AIDifficulty.EASY):
        if candidate.kind == "pass":
            continue
        assert candidate.score == _tactical_score(
            observation, candidate, AIDifficulty.EASY
        )


def test_predicted_damage_never_exceeds_the_best_sequence():
    """规划的口径就是"本回合能打出的最大伤害序列"：火球配斩击时选技能那边。"""
    battle = battle_with_a_combo_choice()
    observation = battle.enemy_observation()
    scores = {
        candidate.card_id or candidate.kind: candidate.score
        for candidate in rank_enemy_actions(observation, AIDifficulty.HARD)
    }

    # 技能（10）+ 斩击（6）= 16 伤，两段连招必须压过单张火球（14 伤）。
    assert scores["skill"] > scores["enemy-fireball"]
    assert scores["enemy-slash"] > scores["enemy-fireball"]
