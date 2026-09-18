from game.battle import BattleState

SESSION_BATTLE_KEY = "battle"


def save_battle(session: dict, battle: BattleState) -> None:
    session[SESSION_BATTLE_KEY] = battle.to_dict()


def load_battle(session: dict) -> BattleState | None:
    payload = session.get(SESSION_BATTLE_KEY)
    if payload is None:
        return None
    return BattleState.from_dict(payload)


def clear_battle(session: dict) -> None:
    session.pop(SESSION_BATTLE_KEY, None)