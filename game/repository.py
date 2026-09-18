import sqlite3
from datetime import datetime, timezone


def init_db(database_path: str) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS match_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hero_key TEXT NOT NULL,
                outcome TEXT NOT NULL,
                turns INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.commit()


def save_match_result(
    database_path: str, hero_key: str, outcome: str, turns: int
) -> None:
    created_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO match_results (hero_key, outcome, turns, created_at) VALUES (?, ?, ?, ?)",
            (hero_key, outcome, turns, created_at),
        )
        connection.commit()
