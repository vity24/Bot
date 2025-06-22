import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'botdb.sqlite')

def get_db():
    return sqlite3.connect(DB_PATH)

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


def get_xp_level(uid: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT xp, level FROM users WHERE id=?", (uid,))
    row = cur.fetchone()
    conn.close()
    if row:
        return row[0], row[1]
    return 0, 1


def update_xp(uid: int, xp: int, level: int, delta: int):
    conn = get_db()
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
