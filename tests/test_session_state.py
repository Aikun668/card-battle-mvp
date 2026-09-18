import random

from game.battle import BattleState
from game.session_state import load_battle, save_battle


def test_saved_battle_round_trips_without_losing_cards_or_phase():
    battle = BattleState.create("mage", random.Random(9))
    session = {}
    save_battle(session, battle)
    restored = load_battle(session)
    assert restored is not None
    assert restored.to_dict() == battle.to_dict()
