from typing import Optional, Dict
import db_pg as db

CARD_FIELDS = [
    "id",
    "name",
    "img",
    "pos",
    "country",
    "born",
    "height",
    "weight",
    "rarity",
    "stats",
    "team_en",
    "team_ru",
]

def get_card(card_id: int) -> Optional[Dict]:
    """Fetch card data directly from the database."""
    conn = db.get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, img, pos, country, born, height, weight, rarity, stats, team_en, team_ru FROM cards WHERE id=?",
        (card_id,),
    )
    row = cur.fetchone()
    conn.close()
    if row:
        return dict(zip(CARD_FIELDS, row))
    return None
