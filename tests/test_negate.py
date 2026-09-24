"""反制（每局一次的场外机会）行为测试。

用双人模式构造（两边都手控）：玩家打出的装备 / 蓄力会挂起，等"对手座位"
决定反制还是放行；人机模式下电脑作为防守方由 AI 自动定夺，不在这些用例里。
"""

import random

from game.ai import AIDifficulty
from game.battle import PENDING_ATTACK, PENDING_PLAY, BattleState
from game.models import BattlePhase, Side


def pvp_battle(player_key="warrior", opponent_key="mage"):
    return BattleState.create(
        player_key,
        random.Random(7),
        AIDifficulty.HARD,
        starting_side=Side.PLAYER,
        mode="pvp",
        opponent_hero_key=opponent_key,
    )


def give_hand(state, side, cards, energy=3):
    participant = state.participant(side)
    participant.hand = cards
    participant.combatant.energy = energy
    return participant


def test_equip_play_pauses_and_negate_cancels_it():
    state = pvp_battle()
    player = give_hand(state, Side.PLAYER, [{"id": "p1", "key": "longsword"}])
    enemy = give_hand(state, Side.ENEMY, [])

    result = state.play_card_for(Side.PLAYER, "p1")

    assert result.ok is True
    assert state.phase is BattlePhase.RESPONSE
    assert state.pending_attack.kind == PENDING_PLAY
    assert player.weapon is None
    # 挂起期间牌已记在弃牌堆：五个牌区任何时刻都守恒。
    assert "longsword" in player.discard_pile

    outcome = state.respond_for(Side.ENEMY, "negate")

    assert outcome.ok is True
    assert state.phase is BattlePhase.PLAYER_TURN
    assert player.weapon is None  # 效果被取消：不进槽
    assert enemy.negate_available is False
    assert enemy.combatant.energy == 2  # 反制花 1 点能量
    assert state.log[-1] == "玩家2使用【反制】，取消了本次效果"


def test_equip_pass_moves_the_card_from_discard_into_the_slot():
    state = pvp_battle()
    player = give_hand(state, Side.PLAYER, [{"id": "p1", "key": "longsword"}])
    give_hand(state, Side.ENEMY, [])

    state.play_card_for(Side.PLAYER, "p1")
    outcome = state.respond_for(Side.ENEMY, "pass")

    assert outcome.ok is True
    assert player.weapon.key == "longsword"
    assert "longsword" not in player.discard_pile  # 从弃牌堆"升华"进槽


def test_charge_play_pauses_and_negate_zeroes_the_bank():
    state = pvp_battle("mage", "warrior")
    player = give_hand(state, Side.PLAYER, [{"id": "p1", "key": "charge"}])
    give_hand(state, Side.ENEMY, [])

    state.play_card_for(Side.PLAYER, "p1")
    assert state.pending_attack.kind == PENDING_PLAY

    assert state.respond_for(Side.ENEMY, "negate").ok is True
    assert player.bonus_energy_next_turn == 0


def test_negate_chance_is_once_per_game():
    state = pvp_battle()
    give_hand(state, Side.PLAYER, [{"id": "p1", "key": "longsword"}])
    enemy = give_hand(state, Side.ENEMY, [])

    state.play_card_for(Side.PLAYER, "p1")
    state.respond_for(Side.ENEMY, "negate")
    assert enemy.negate_available is False

    # 第二次出装备：机会已用，不挂起、直接落地。
    give_hand(state, Side.PLAYER, [{"id": "p2", "key": "iron_armor"}])
    state.play_card_for(Side.PLAYER, "p2")

    assert state.phase is BattlePhase.PLAYER_TURN
    assert state.participant(Side.PLAYER).armor.key == "iron_armor"


def test_no_pause_without_the_negate_chance_or_energy():
    # 机会本身不在（被标记为已用）→ 不挂起。
    state = pvp_battle()
    give_hand(state, Side.PLAYER, [{"id": "p1", "key": "longsword"}])
    enemy = give_hand(state, Side.ENEMY, [])
    enemy.negate_available = False
    state.play_card_for(Side.PLAYER, "p1")
    assert state.phase is BattlePhase.PLAYER_TURN
    assert state.participant(Side.PLAYER).weapon.key == "longsword"

    # 机会还在、但付不起 1 费 → 也不挂起。
    state2 = pvp_battle()
    give_hand(state2, Side.PLAYER, [{"id": "p1", "key": "longsword"}])
    enemy2 = give_hand(state2, Side.ENEMY, [], energy=0)
    state2.play_card_for(Side.PLAYER, "p1")
    assert state2.phase is BattlePhase.PLAYER_TURN
    assert state2.participant(Side.PLAYER).weapon.key == "longsword"
    assert enemy2.negate_available is True  # 没用掉


def test_damage_attacks_keep_using_dodge_not_negate():
    state = pvp_battle("warrior", "warrior")
    give_hand(state, Side.PLAYER, [{"id": "p1", "key": "slash"}])
    enemy = give_hand(state, Side.ENEMY, [{"id": "e1", "key": "dodge"}])
    hp_before = enemy.combatant.hp

    state.play_card_for(Side.PLAYER, "p1")

    assert state.pending_attack.kind == PENDING_ATTACK
    # 伤害挂起时不能用反制、也不该用；闪避照常。
    assert state.respond_for(Side.ENEMY, "negate").ok is False
    assert state.respond_for(Side.ENEMY, "dodge").ok is True
    assert enemy.combatant.hp == hp_before
