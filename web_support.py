from flask import current_app

from game.battle import BattleState
from game.repository import save_match_result
from game.session_state import save_battle

RESULT_SAVED_KEY = "match_result_saved"


def persist_battle(session: dict, battle: BattleState) -> None:
    save_battle(session, battle)
    if battle.is_finished() and not session.get(RESULT_SAVED_KEY):
        save_match_result(
            current_app.config["DATABASE"],
            battle.hero.key,
            battle.phase.value,
            battle.round_number,
        )
        session[RESULT_SAVED_KEY] = True
