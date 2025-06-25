import os
import json
import psycopg2
from dotenv import load_dotenv

load_dotenv()

class PGCursor:
    def __init__(self, cur):
        self._cur = cur
    def execute(self, query, params=None):
        if params is None:
            params = ()
        # psycopg2 uses the pyformat style for placeholders. Our SQL queries
        # were originally written for SQLite and may contain ``?`` placeholders
        # as well as percent signs used in ``LIKE`` patterns.  Percent signs not
        # belonging to placeholders must be doubled, otherwise ``psycopg2``
        # tries to treat them as formatting tokens which results in errors such
        # as ``IndexError: tuple index out of range``.  Convert the placeholders
        # and escape raw percent signs before executing the query.
        query = query.replace('%', '%%').replace('?', '%s')
        self._cur.execute(query, params)
    def executemany(self, query, seq):
        query = query.replace('%', '%%').replace('?', '%s')
        self._cur.executemany(query, seq)
    def fetchone(self):
        return self._cur.fetchone()
    def fetchall(self):
        return self._cur.fetchall()
    def __iter__(self):
        return iter(self._cur)
    def close(self):
        self._cur.close()

class PGConnection:
    def __init__(self, conn):
        self._conn = conn
    def cursor(self):
        return PGCursor(self._conn.cursor())
    def execute(self, query, params=None):
        cur = self.cursor()
        cur.execute(query, params)
        return cur
    def commit(self):
        self._conn.commit()
    def close(self):
        self._conn.close()


def get_db():
    conn = psycopg2.connect(
        host=os.getenv('PG_HOST'),
        port=os.getenv('PG_PORT'),
        dbname=os.getenv('PG_DB'),
        user=os.getenv('PG_USER'),
        password=os.getenv('PG_PASSWORD'),
    )
    return PGConnection(conn)


def setup_battle_db():
    conn = get_db()
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS battles (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            opponent TEXT,
            result TEXT,
            score_team1 INTEGER,
            score_team2 INTEGER,
            mvp TEXT,
            log TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
    conn.commit()
    conn.close()


def save_battle_result(user_id, opponent_name, result):
    conn = get_db()
    conn.execute(
        '''
        INSERT INTO battles (user_id, opponent, result, score_team1, score_team2, mvp, log)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''',
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
    cur = conn.execute(
        '''SELECT timestamp, opponent, result, score_team1, score_team2, mvp
           FROM battles WHERE user_id=? ORDER BY id DESC LIMIT ?''',
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
        (
            'INSERT INTO teams (user_id, name, lineup, bench) '
            'VALUES (?, ?, ?, ?) '
            'ON CONFLICT (user_id) '
            'DO UPDATE SET name=EXCLUDED.name, '
            'lineup=EXCLUDED.lineup, bench=EXCLUDED.bench'
        ),
        (user_id, name, json.dumps(lineup), json.dumps(bench)),
    )
    conn.commit()
    conn.close()


def get_team(user_id):
    conn = get_db()
    cur = conn.execute(
        'SELECT name, lineup, bench FROM teams WHERE user_id=?',
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()
    if row:
        return {
            'name': row[0],
            'lineup': json.loads(row[1] or '[]'),
            'bench': json.loads(row[2] or '[]'),
        }
    return None


def team_name_taken(name: str, exclude_user_id: int) -> bool:
    conn = get_db()
    cur = conn.execute(
        'SELECT user_id FROM teams WHERE name=? AND user_id != ?',
        (name, exclude_user_id),
    )
    row = cur.fetchone()
    conn.close()
    return row is not None


def get_xp_level(uid: int):
    conn = get_db()
    cur = conn.execute('SELECT xp, level FROM users WHERE id=?', (uid,))
    row = cur.fetchone()
    conn.close()
    if row:
        return row[0], row[1]
    return 0, 1


def update_xp(uid: int, xp: int, level: int, delta: int):
    conn = get_db()
    conn.execute(
        'UPDATE users SET xp=?, level=?, xp_daily = xp_daily + ?, last_xp_reset=last_xp_reset WHERE id=?',
        (xp, level, delta, uid),
    )
    conn.commit()
    conn.close()


def reset_daily_xp():
    conn = get_db()
    conn.execute(
        "UPDATE users SET xp_daily=0, last_xp_reset=CURRENT_DATE WHERE last_xp_reset < CURRENT_DATE"
    )
    conn.commit()
    conn.close()


def get_win_streak(uid: int) -> int:
    conn = get_db()
    cur = conn.execute('SELECT win_streak FROM users WHERE id=?', (uid,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0


def update_win_streak(uid: int, won: bool):
    streak = get_win_streak(uid)
    streak = streak + 1 if won else 0
    conn = get_db()
    conn.execute('UPDATE users SET win_streak=? WHERE id=?', (streak, uid))
    conn.commit()
    conn.close()
    return streak
