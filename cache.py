"""Shared caching utilities for card data."""

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

CARD_CACHE: dict[int, dict] = {}


def load_card_cache(force: bool = False) -> None:
    """Load all cards into memory to reduce database lookups."""
    global CARD_CACHE
    if CARD_CACHE and not force:
        return
    conn = db.get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, img, pos, country, born, height, weight, rarity, stats, team_en, team_ru FROM cards"
    )
    rows = cur.fetchall()
    conn.close()
    CARD_CACHE = {row[0]: dict(zip(CARD_FIELDS, row)) for row in rows}


def get_card_from_cache(card_id: int):
    """Return card data from cache and fetch from DB on miss."""
    if card_id not in CARD_CACHE:
        conn = db.get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, img, pos, country, born, height, weight, rarity, stats, team_en, team_ru FROM cards WHERE id=?",
            (card_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            CARD_CACHE[card_id] = dict(zip(CARD_FIELDS, row))
        else:
            return None
    return CARD_CACHE.get(card_id)


def refresh_card_cache(card_id: int) -> None:
    """Refresh cached data for a specific card or remove it."""
    conn = db.get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, img, pos, country, born, height, weight, rarity, stats, team_en, team_ru FROM cards WHERE id=?",
        (card_id,),
    )
    row = cur.fetchone()
    conn.close()
    if row:
        CARD_CACHE[card_id] = dict(zip(CARD_FIELDS, row))
    else:
        CARD_CACHE.pop(card_id, None)


def invalidate_score_cache_for_card(card_id: int) -> None:
    """Reset cached scores and ranks for users owning the given card."""
    conn = db.get_db()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT user_id FROM inventory WHERE card_id=?", (card_id,))
    user_ids = [row[0] for row in cur.fetchall()]
    conn.close()

    import bot

    for uid in user_ids:
        bot.SCORE_CACHE.pop(uid, None)
        bot.RANK_CACHE.pop(uid, None)
    # reset top cache so high scores recompute
    bot.TOP_CACHE = ([], 0)

