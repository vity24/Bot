import os
import sqlite3
import psycopg2
from dotenv import load_dotenv

load_dotenv()

SQLITE_DB = os.path.join(os.path.dirname(__file__), 'botdb.sqlite')

pg_conn = psycopg2.connect(
    host=os.getenv('PG_HOST'),
    port=os.getenv('PG_PORT'),
    dbname=os.getenv('PG_DB'),
    user=os.getenv('PG_USER'),
    password=os.getenv('PG_PASSWORD'),
)
pg_cur = pg_conn.cursor()

# Создание таблиц с нужными типами
pg_cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY,
    username TEXT,
    last_card_time BIGINT,
    last_week_score INTEGER,
    referrals_count INTEGER,
    invited_by BIGINT,
    xp INTEGER,
    level INTEGER,
    xp_daily INTEGER,
    last_xp_reset DATE,
    win_streak INTEGER
)
""")

pg_cur.execute("""
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY,
    name TEXT,
    img TEXT,
    pos TEXT,
    country TEXT,
    born TEXT,
    height TEXT,
    weight TEXT,
    rarity TEXT,
    stats TEXT,
    team_en TEXT,
    team_ru TEXT,
    points INTEGER,
    upgrade INTEGER,
    power INTEGER,
    updated_at TIMESTAMP
)
""")

pg_cur.execute("""
CREATE TABLE IF NOT EXISTS inventory (
    user_id BIGINT,
    card_id INTEGER,
    time_got BIGINT
)
""")

pg_cur.execute("""
CREATE TABLE IF NOT EXISTS teams (
    user_id BIGINT PRIMARY KEY,
    name TEXT,
    lineup TEXT,
    bench TEXT
)
""")

pg_cur.execute("""
CREATE TABLE IF NOT EXISTS battles (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    opponent TEXT,
    result TEXT,
    score_team1 INTEGER,
    score_team2 INTEGER,
    mvp TEXT,
    log TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

pg_conn.commit()

# Перенос данных из SQLite
sqlite_conn = sqlite3.connect(SQLITE_DB)
sqlite_cur = sqlite_conn.cursor()

TABLES = ['users', 'cards', 'inventory', 'teams', 'battles']
for table in TABLES:
    sqlite_cur.execute(f'SELECT * FROM {table}')
    rows = sqlite_cur.fetchall()
    if not rows:
        continue
    cols = [desc[0] for desc in sqlite_cur.description]

    if table == "cards" and "updated_at" in cols:
        ts_index = cols.index("updated_at")
        placeholders_list = ['%s' if i != ts_index else 'to_timestamp(%s)' for i in range(len(cols))]
        placeholders = ','.join(placeholders_list)
    else:
        placeholders = ','.join(['%s'] * len(cols))

    col_list = ', '.join(cols)
    insert_q = f'INSERT INTO {table} ({col_list}) VALUES ({placeholders})'

    for row in rows:
        try:
            pg_cur.execute("BEGIN;")
            pg_cur.execute(insert_q, row)
            pg_cur.execute("COMMIT;")
        except Exception as e:
            pg_cur.execute("ROLLBACK;")
            print(f"Ошибка при вставке в {table}: {e}\n{row}")

pg_conn.commit()
pg_conn.close()
sqlite_conn.close()
