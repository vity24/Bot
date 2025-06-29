import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'botdb.sqlite')

def get_db():
    return sqlite3.connect(DB_PATH)

def _ensure_user_columns(conn):
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(users)")
    cols = {row[1] for row in cur.fetchall()}
    if 'xp' not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN xp INTEGER DEFAULT 0")
    if 'level' not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN level INTEGER DEFAULT 1")
    if 'xp_daily' not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN xp_daily INTEGER DEFAULT 0")
    if 'last_xp_reset' not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN last_xp_reset DATE")
        cur.execute("UPDATE users SET last_xp_reset = DATE('now') WHERE last_xp_reset IS NULL")
    if 'win_streak' not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN win_streak INTEGER DEFAULT 0")
    conn.commit()

def setup_battle_db():
    conn = get_db()
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS battles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            opponent TEXT,
            result TEXT,
            score_team1 INTEGER,
            score_team2 INTEGER,
            mvp TEXT,
            log TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
    conn.commit()
    conn.close()


def save_battle_result(user_id, opponent_name, result):
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS battles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            opponent TEXT,
            result TEXT,
            score_team1 INTEGER,
            score_team2 INTEGER,
            mvp TEXT,
            log TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        INSERT INTO battles (user_id, opponent, result, score_team1, score_team2, mvp, log)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            opponent_name,
            result["winner"],
            result["score"]["team1"],
            result["score"]["team2"],
            result["mvp"],
            json.dumps(result["log"]),
        ),
    )
    conn.commit()
    conn.close()


def get_battle_history(user_id, limit=5):
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS battles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            opponent TEXT,
            result TEXT,
            score_team1 INTEGER,
            score_team2 INTEGER,
            mvp TEXT,
            log TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur = conn.cursor()
    cur.execute(
        """SELECT timestamp, opponent, result, score_team1, score_team2, mvp
           FROM battles WHERE user_id=? ORDER BY id DESC LIMIT ?""",
        (user_id, limit),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def setup_team_db():
    conn = get_db()
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS teams (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            lineup TEXT,
            bench TEXT
        )
        '''
    )
    conn.commit()
    conn.close()


def save_team(user_id, name, lineup, bench):
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS teams (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            lineup TEXT,
            bench TEXT
        )
        """
    )
    conn.execute(
        "REPLACE INTO teams (user_id, name, lineup, bench) VALUES (?, ?, ?, ?)",
        (user_id, name, json.dumps(lineup), json.dumps(bench)),
    )
    conn.commit()
    conn.close()


def get_team(user_id):
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS teams (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            lineup TEXT,
            bench TEXT
        )
        """
    )
    cur = conn.cursor()
    cur.execute("SELECT name, lineup, bench FROM teams WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        return {
            "name": row[0],
            "lineup": json.loads(row[1] or "[]"),
            "bench": json.loads(row[2] or "[]"),
        }
    return None


def team_name_taken(name: str, exclude_user_id: int) -> bool:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id FROM teams WHERE name=? AND user_id != ?",
        (name, exclude_user_id),
    )
    row = cur.fetchone()
    conn.close()
    return row is not None


def get_xp_level(uid: int):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT xp, level FROM users WHERE id=?", (uid,))
    except sqlite3.OperationalError:
        _ensure_user_columns(conn)
        cur.execute("SELECT xp, level FROM users WHERE id=?", (uid,))
    row = cur.fetchone()
    conn.close()
    if row:
        xp = row[0] if row[0] is not None else 0
        lvl = row[1] if row[1] is not None else 1
        return xp, lvl
    return 0, 1


def update_xp(uid: int, xp: int, level: int, delta: int):
    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET xp=?, level=?, xp_daily = xp_daily + ?, last_xp_reset=last_xp_reset WHERE id=?",
            (xp, level, delta, uid),
        )
    except sqlite3.OperationalError:
        _ensure_user_columns(conn)
        conn.execute(
            "UPDATE users SET xp=?, level=?, xp_daily = xp_daily + ?, last_xp_reset=last_xp_reset WHERE id=?",
            (xp, level, delta, uid),
        )
    conn.commit()
    conn.close()


def reset_daily_xp():
    conn = get_db()
    conn.execute(
        "UPDATE users SET xp_daily=0, last_xp_reset=DATE('now') WHERE last_xp_reset < DATE('now')"
    )
    conn.commit()
    conn.close()


def get_win_streak(uid: int) -> int:
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT win_streak FROM users WHERE id=?", (uid,))
        row = cur.fetchone()
    except sqlite3.OperationalError:
        row = None
    conn.close()
    return row[0] if row else 0


def update_win_streak(uid: int, won: bool):
    streak = get_win_streak(uid)
    streak = streak + 1 if won else 0
    conn = get_db()
    conn.execute("UPDATE users SET win_streak=? WHERE id=?", (streak, uid))
    conn.commit()
    conn.close()
    return streak


def get_all_players(limit: int = 20):
    """Return a list of player ``(id, name)`` tuples ordered by name."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name FROM cards ORDER BY name LIMIT ?",
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def update_player_name(player_id: int, new_name: str) -> None:
    """Update player's name in the database."""
    conn = get_db()
    conn.execute(
        "UPDATE cards SET name=? WHERE id=?",
        (new_name, player_id),
    )
    conn.commit()
    conn.close()
