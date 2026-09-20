import random

from game.battle import BattleState
from game.models import AIDifficulty
from game.session_state import clear_battle, load_battle, save_battle


def test_saved_battle_round_trips_without_losing_cards_or_phase():
    battle = BattleState.create("mage", random.Random(9))
    session = {}
    save_battle(session, battle)
    restored = load_battle(session)
    assert restored is not None
    assert restored.to_dict() == battle.to_dict()


def test_saved_battle_round_trips_the_ai_difficulty():
    session = {}
    save_battle(
        session, BattleState.create("mage", random.Random(9), AIDifficulty.HARD)
    )
    assert load_battle(session).ai_difficulty is AIDifficulty.HARD


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
