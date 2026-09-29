import sqlite3
from datetime import datetime, timezone

# 在线 PvP 的三张表。时间统一存 UTC ISO 8601 文本；battle_state_json 只保存
# 能由 BattleState.from_dict() 还原的数据。所有语句必须可重复执行。
_ONLINE_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS online_rooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_id TEXT NOT NULL UNIQUE,
        room_code TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL,
        match_number INTEGER NOT NULL,
        revision INTEGER NOT NULL,
        battle_state_json TEXT,
        result_saved_match_number INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_online_rooms_expires_at "
    "ON online_rooms (expires_at)",
    """
    CREATE TABLE IF NOT EXISTS online_room_players (
        room_id TEXT NOT NULL,
        seat TEXT NOT NULL CHECK (seat IN ('player', 'enemy')),
        nickname TEXT NOT NULL,
        token_hash TEXT NOT NULL,
        selected_hero_key TEXT,
        rematch_confirmed_for INTEGER,
        joined_at TEXT NOT NULL,
        PRIMARY KEY (room_id, seat),
        FOREIGN KEY (room_id) REFERENCES online_rooms (room_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS online_match_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_id TEXT NOT NULL,
        match_number INTEGER NOT NULL,
        player_hero_key TEXT NOT NULL,
        enemy_hero_key TEXT NOT NULL,
        winner TEXT,
        result_reason TEXT NOT NULL,
        turns INTEGER NOT NULL,
        finished_at TEXT NOT NULL,
        UNIQUE (room_id, match_number)
    )
    """,
)


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
        for statement in _ONLINE_SCHEMA:
            connection.execute(statement)
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
