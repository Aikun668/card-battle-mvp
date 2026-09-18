import sqlite3

from game.repository import init_db, save_match_result


def test_save_match_result_creates_a_queryable_row(tmp_path):
    database_path = tmp_path / "card_battle.sqlite3"
    init_db(str(database_path))
    save_match_result(str(database_path), "warrior", "VICTORY", 4)
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT hero_key, outcome, turns FROM match_results"
        ).fetchone()
    assert row == ("warrior", "VICTORY", 4)