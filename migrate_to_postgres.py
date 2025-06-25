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

sqlite_conn = sqlite3.connect(SQLITE_DB)
sqlite_cur = sqlite_conn.cursor()

TABLES = ['users', 'cards', 'inventory', 'teams', 'battles']
for table in TABLES:
    sqlite_cur.execute(f'SELECT * FROM {table}')
    rows = sqlite_cur.fetchall()
    if not rows:
        continue
    cols = [desc[0] for desc in sqlite_cur.description]
    placeholders = ','.join(['%s'] * len(cols))
    col_list = ', '.join(cols)
    insert_q = f'INSERT INTO {table} ({col_list}) VALUES ({placeholders})'
    for row in rows:
        pg_cur.execute(insert_q, row)

pg_conn.commit()
pg_conn.close()
sqlite_conn.close()
