import random

from game.battle import BattleState
from game.catalog import HEROES
from game.models import AIDifficulty, BattlePhase, PendingAttack, Side
from game.session_state import clear_battle, load_battle, save_battle

LEGACY_PAYLOAD = {
    "hero": {
        "key": "warrior",
        "name": "战士",
        "max_hp": 32,
        "skill_name": "守护",
        "skill_type": "shield",
        "skill_value": 8,
    },
    "player": {"name": "战士", "max_hp": 32, "hp": 24, "shield": 3, "energy": 2},
    "enemy": {"name": "电脑", "max_hp": 28, "hp": 28, "shield": 0, "energy": 0},
    "hand": [{"id": "p-1", "key": "slash"}],
    "draw_pile": ["heal", "fireball"],
    "discard_pile": ["shield"],
    "enemy_hand": [{"id": "e-1", "key": "heavy_strike"}],
    "enemy_draw_pile": ["slash"],
    "enemy_discard_pile": [],
    "round_number": 4,
    "phase": "PLAYER_TURN",
    "log": ["第 4 回合开始"],
    "skill_used_this_turn": True,
    "pending_attack": None,
    "ai_difficulty": "hard",
}


def test_saved_battle_round_trips_without_losing_cards_or_phase():
    battle = BattleState.create("mage", random.Random(9))
    session = {}
    save_battle(session, battle)
    restored = load_battle(session)
    assert restored is not None
    assert restored.to_dict() == battle.to_dict()


def test_saved_payload_uses_the_participant_structure_only():
    battle = BattleState.create("mage", random.Random(9))
    payload = battle.to_dict()
    assert set(payload["participants"]) == {"player", "enemy"}
    assert payload["participants"]["enemy"]["hero_key"] == battle.enemy_hero.key
    for legacy_key in ("hand", "draw_pile", "discard_pile", "enemy_hand", "hero"):
        assert legacy_key not in payload


def test_saved_battle_round_trips_both_heroes_and_turn_owner():
    battle = BattleState.create("mage", random.Random(9), starting_side=Side.ENEMY)
    restored = BattleState.from_dict(battle.to_dict())
    assert restored.hero.key == "mage"
    assert restored.enemy_hero.key == battle.enemy_hero.key
    assert restored.starting_side is Side.ENEMY
    assert restored.round_number == battle.round_number
    assert restored.log == battle.log


def test_old_session_payload_migrates_with_a_valid_enemy_hero():
    restored = BattleState.from_dict(dict(LEGACY_PAYLOAD))
    assert restored.hero.key == "warrior"
    assert restored.enemy_hero.key in HEROES
    assert restored.enemy.max_hp == HEROES[restored.enemy_hero.key].max_hp
    assert restored.player.hp == 24
    assert restored.player.shield == 3
    assert restored.player.energy == 2
    assert restored.round_number == 4
    assert restored.phase is BattlePhase.PLAYER_TURN
    assert restored.skill_used_this_turn is True
    assert restored.ai_difficulty is AIDifficulty.HARD
    assert len(restored.hand) == 1
    assert restored.enemy_draw_pile == ["slash"]


def test_old_session_payload_keeps_the_enemy_health_within_its_hero_range():
    payload = dict(LEGACY_PAYLOAD)
    payload["enemy"] = {
        "name": "电脑",
        "max_hp": 28,
        "hp": 999,
        "shield": 0,
        "energy": 0,
    }
    restored = BattleState.from_dict(payload)
    assert restored.enemy.hp == HEROES[restored.enemy_hero.key].max_hp


def test_saved_battle_round_trips_the_ai_difficulty():
    session = {}
    save_battle(
        session, BattleState.create("mage", random.Random(9), AIDifficulty.HARD)
    )
    assert load_battle(session).ai_difficulty is AIDifficulty.HARD


def test_saved_battle_round_trips_a_pending_attack_from_either_side():
    battle = BattleState.create("warrior", random.Random(9), starting_side=Side.PLAYER)
    battle.pending_attack = PendingAttack(
        attacker=Side.PLAYER,
        defender=Side.ENEMY,
        card_key="heavy_strike",
        card_name="重击",
        damage=10,
    )

    restored = BattleState.from_dict(battle.to_dict())

    assert restored.pending_attack == battle.pending_attack
    assert restored.pending_attack.attacker is Side.PLAYER
    assert restored.pending_attack.defender is Side.ENEMY


def test_old_pending_attack_payload_still_reads_as_the_enemy_attacking_the_player():
    payload = dict(LEGACY_PAYLOAD)
    payload["pending_attack"] = {
        "card_key": "heavy_strike",
        "card_name": "重击",
        "damage": 10,
    }

    restored = BattleState.from_dict(payload)

    assert restored.pending_attack.attacker is Side.ENEMY
    assert restored.pending_attack.defender is Side.PLAYER
    assert restored.pending_attack.damage == 10


def test_load_battle_without_a_saved_game_returns_none():
    assert load_battle({}) is None


def test_load_battle_defaults_to_medium_when_the_difficulty_field_is_missing():
    # 本次改动之前保存的对局没有难度字段，读到旧 session 不能崩。
    session = {}
    save_battle(session, BattleState.create("mage", random.Random(9)))
    del session["battle"]["ai_difficulty"]
    assert load_battle(session).ai_difficulty is AIDifficulty.MEDIUM


def test_clear_battle_removes_the_saved_game():
    session = {}
    save_battle(session, BattleState.create("mage", random.Random(9)))
    clear_battle(session)
    assert load_battle(session) is None
