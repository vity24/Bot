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
    cur = conn.cursor()
    cur.execute(
        """SELECT timestamp, opponent, result, score_team1, score_team2, mvp
           FROM battles WHERE user_id=? ORDER BY id DESC LIMIT ?""",
        (user_id, limit),
    )
    rows = cur.fetchall()
    conn.close()
    return rows
