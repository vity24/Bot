import os
import time
import random
import re
import asyncio
import logging
import telegram
import datetime

sub_cache: dict[int, tuple[bool, float]] = {}
SUB_TTL = 30  # секунд

async def is_user_subscribed(bot, user_id):
    cached = sub_cache.get(user_id, (None, 0))
    ok, ts = cached
    if ok is not None and time.time() - ts < SUB_TTL:
        return ok
    try:
        for ch in CHANNELS:
            member = await bot.get_chat_member(ch["username"], user_id)
            if member.status not in ("member", "administrator", "creator"):
                sub_cache[user_id] = (False, time.time())
                return False
        sub_cache[user_id] = (True, time.time())
        return True
    except telegram.error.RetryAfter as e:
        await asyncio.sleep(e.retry_after)
        return await is_user_subscribed(bot, user_id)
    except Exception:
        sub_cache[user_id] = (False, time.time())
        return False
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    DictPersistence,
)
from telegram.error import BadRequest, NetworkError
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
    Update,
    InputMediaPhoto,
)
from telegram.helpers import escape_markdown
from collections import Counter
from functools import wraps
import handlers
import db_pg as db
from helpers.leveling import xp_to_next
from helpers import shorten_number, format_ranking_row, format_my_rank
from helpers.normalize_stats import normalize_stats_input
from helpers.styles import get_player_style
from helpers.permissions import ADMINS, is_admin, admin_only
from helpers.admin_utils import (
    record_admin_usage,
    admin_usage_log,
    admin_usage_count,
    admin_action_history,
    banned_users,
    online_users,
)

async def check_subscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if await is_user_subscribed(context.bot, user_id):
        try:
            await query.delete_message()
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "🎉 Подписка на оба канала подтверждена!\n\n"
                "Теперь доступен весь функционал бота. Введи /start или выбери команду из меню."
            )
        )
    else:
        await query.answer("❗️ Подпишись на оба канала и попробуй снова.", show_alert=True)

def require_subscribe(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        # вот тут — если админ, не проверяем подписку
        if is_admin(user_id):
            return await func(update, context, *args, **kwargs)
        if not await is_user_subscribed(context.bot, user_id):
            await start(update, context)
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


class _UpdateWrapper:
    """Proxy Update that exposes callback message as ``message`` attribute."""

    __slots__ = ("_orig",)

    def __init__(self, update: Update) -> None:
        self._orig = update

    def __getattr__(self, name):
        if name == "message":
            return self._orig.callback_query.message
        return getattr(self._orig, name)


async def _call_with_query_message(func, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Call ``func`` with a proxy so it can use ``update.message``."""
    if getattr(update, "callback_query", None):
        await update.callback_query.answer()
        return await func(_UpdateWrapper(update), context)
    return await func(update, context)


TOKEN = "7649956181:AAErINkWzZJ7BofoorAHxc2fLXMPoaCjkQM"
CARD_COOLDOWN = 3 * 60 * 60  # 3 часа
CHANNELS = [
    {"username": "@HOCKEY_CARDS_NHL", "name": "Подпишись на канал", "link": "https://t.me/HOCKEY_CARDS_NHL"},
    {"username": "@Hockey_cards_nhl_chat", "name": "Подпишись на чат", "link": "https://t.me/Hockey_cards_nhl_chat"}
]


RARITY_RU = {
    "legendary": "Легендарная ⭐️",
    "mythic":    "Мифическая 🟥",
    "epic":      "Эпическая 💎",
    "rare":      "Редкая 🔵",
    "common":    "Обычная 🟢",
}

# Short versions without emoji
RARITY_RU_SHORT = {
    "legendary": "Легендарная",
    "mythic": "Мифическая",
    "epic": "Эпическая",
    "rare": "Редкая",
    "common": "Обычная",
}

# Plural forms for grouped lists
RARITY_RU_PLURAL = {
    "legendary": "Легендарные",
    "mythic": "Мифические",
    "epic": "Эпические",
    "rare": "Редкие",
    "common": "Обычные",
}

RARITY_ORDER = {
    "legendary": 0,
    "mythic": 1,
    "epic": 2,
    "rare": 3,
    "common": 4
}

RARITY_EMOJI = {
    "legendary": "⭐️",
    "mythic": "🟥",
    "epic": "💎",
    "rare": "🔵",
    "common": "🟢",
}

RARITY_WEIGHTS = {
    "legendary": 1,
    "mythic":    2,
    "epic":      6,
    "rare":      18,
    "common":    73,
}

RARITY_MULTIPLIERS = {
    "common": 1,
    "rare": 1.3,
    "epic": 1.8,
    "mythic": 2.5,
    "legendary": 4
}

# --- Dynamic intro and main menu helpers ---
def get_dynamic_intro() -> str:
    hour = datetime.datetime.now().hour
    if 5 <= hour < 11:
        time_greeting = "☀️ Утро чемпиона!"
    elif 11 <= hour < 18:
        time_greeting = "🏒 Днём выигрывают серии!"
    elif 18 <= hour < 23:
        time_greeting = "🌇 Вечер для легенд!"
    else:
        time_greeting = "🌙 Ночь — время сбора карт..."

    phrases = [
        "🔥 Толпа скандирует твоё имя...",
        "🎯 Время показать класс!",
        "🧊 Ты входишь на лёд...",
        "⚡️ Заряд энергии: 100%",
        "🤖 Скауты уже следят за тобой...",
        "🏆 Карточка ждёт своего героя...",
        "📢 Соперники нервно молчат...",
    ]
    random.shuffle(phrases)
    return f"{time_greeting}\n{phrases[0]}\n{phrases[1]}"


async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.first_name or "Игрок"

    xp, level = db.get_xp_level(user_id)
    to_next = xp_to_next(xp)
    score = int(await get_user_score_cached(user_id))
    rank, total = await get_user_rank_cached(user_id)
    unique_cards, total_cards = get_inventory_counts(user_id)
    referrals = get_referral_count(user_id)
    streak = db.get_win_streak(user_id)

    intro_text = get_dynamic_intro()

    if rank <= 3:
        phrase = "🏆 Ты в ТРОЙКЕ лучших коллекционеров!"
    elif rank <= 10:
        phrase = "🔥 Ты в ТОП-10 — продолжаем в том же духе!"
    elif total_cards > 100:
        phrase = "📦 У тебя уже сотня карт! Уважение."
    elif referrals >= 5:
        phrase = "🎯 Ты привёл кучу друзей — красавчик!"
    else:
        phrase = "⚡️ Готов к новым карточкам и боям?"

    menu_text = (
        f"{intro_text}\n\n"
        f"👤 *{username}*  |  Уровень: *{level}*\n"
        f"📊 Очки: *{score}*  |  Ранг: *#{rank} из {total}*\n"
        f"📦 Карт: *{total_cards}*  |  Уник: *{unique_cards}*\n"
        f"🔥 Побед подряд: *{streak}*\n"
        f"👥 Друзей привёл: *{referrals}*\n\n"
        f"{phrase}\n\n"
        "👇 Выбирай, чем заняться:"
    )

    buttons = [
        [InlineKeyboardButton("🃏 Получить карточку", callback_data="menu_card")],
        [InlineKeyboardButton("📦 Моя коллекция", callback_data="menu_collection")],
        [InlineKeyboardButton("👤 Профиль и рейтинг", callback_data="menu_me")],
        [
            InlineKeyboardButton("⚔️ Бой с ботом", callback_data="menu_fight"),
            InlineKeyboardButton("🆚 Дуэль", callback_data="menu_duel"),
        ],
        [InlineKeyboardButton("🧠 Рейтинг игроков", callback_data="menu_rank")],
        [InlineKeyboardButton("🔄 Обмен картами", callback_data="menu_trade")],
        [InlineKeyboardButton("🎁 Пригласить друга", callback_data="menu_invite")],
    ]
    if is_admin(user_id):
        buttons.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="menu_admin")])
    markup = InlineKeyboardMarkup(buttons)

    await update.message.reply_text(menu_text, reply_markup=markup, parse_mode="Markdown")


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle main menu inline buttons."""
    data = update.callback_query.data
    mapping = {
        "menu_card": card,
        "menu_collection": collection,
        "menu_me": me,
        "menu_fight": handlers.start_fight,
        "menu_duel": handlers.start_duel,
        "menu_rank": rank,
        "menu_trade": trade_info,
        "menu_invite": invite,
        "menu_history": handlers.show_battle_history,
        "menu_back": menu,
        "menu_admin": admin_panel,
    }
    func = mapping.get(data)
    if func:
        await _call_with_query_message(func, update, context)
    else:
        await update.callback_query.answer()


# --- Кэш для карточек ---
CARD_FIELDS = [
    "id", "name", "img", "pos", "country", "born", "height",
    "weight", "rarity", "stats", "team_en", "team_ru"
]
CARD_CACHE = {}
RANK_CACHE: dict[int, tuple[int, int, float]] = {}
SCORE_CACHE: dict[int, tuple[float, float]] = {}
TOP_CACHE: tuple[list[tuple[int, str | None, float, int]], float] = ([], 0)
RANK_TTL = 600  # seconds
SCORE_TTL = 600  # seconds
TOP_TTL = 600  # seconds

def load_card_cache(force=False):
    """Загружаем все карточки в память для сокращения обращений к БД."""
    global CARD_CACHE
    if CARD_CACHE and not force:
        return
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT id, name, img, pos, country, born, height, weight, rarity, stats, team_en, team_ru FROM cards"
    )
    rows = c.fetchall()
    conn.close()
    CARD_CACHE = {
        row[0]: dict(zip(CARD_FIELDS, row))
        for row in rows
    }

def get_card_from_cache(card_id):
    """Возвращает информацию о карте из кэша, при необходимости подгружает её."""
    if card_id not in CARD_CACHE:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT id, name, img, pos, country, born, height, weight, rarity, stats, team_en, team_ru FROM cards WHERE id=?",
            (card_id,),
        )
        row = c.fetchone()
        conn.close()
        if row:
            CARD_CACHE[card_id] = dict(zip(CARD_FIELDS, row))
        else:
            return None
    return CARD_CACHE.get(card_id)

def refresh_card_cache(card_id):
    """Обновляем кэш для конкретной карты или очищаем её."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT id, name, img, pos, country, born, height, weight, rarity, stats, team_en, team_ru FROM cards WHERE id=?",
        (card_id,),
    )
    row = c.fetchone()
    conn.close()
    if row:
        CARD_CACHE[card_id] = dict(zip(CARD_FIELDS, row))
    else:
        CARD_CACHE.pop(card_id, None)

def invalidate_score_cache_for_card(card_id: int) -> None:
    """Reset cached scores and ranks for users owning the given card."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT user_id FROM inventory WHERE card_id=?", (card_id,))
    user_ids = [row[0] for row in cur.fetchall()]
    conn.close()
    for uid in user_ids:
        SCORE_CACHE.pop(uid, None)
        RANK_CACHE.pop(uid, None)
    globals()['TOP_CACHE'] = ([], 0)

POS_RU = {
    "C": "Центр",
    "LW": "Левый нап.",
    "RW": "Правый нап.",
    "D": "Защитник",
    "G": "Вратарь"
}

ISO3_TO_FLAG = {
    "CAN": "🇨🇦", "USA": "🇺🇸", "RUS": "🇷🇺", "FIN": "🇫🇮", "SWE": "🇸🇪",
    "CZE": "🇨🇿", "SVK": "🇸🇰", "DEU": "🇩🇪", "GER": "🇩🇪", "CHE": "🇨🇭",
    "AUT": "🇦🇹", "DNK": "🇩🇰", "DEN": "🇩🇰", "NLD": "🇳🇱", "NOR": "🇳🇴",
    "LVA": "🇱🇻", "BLR": "🇧🇾", "UKR": "🇺🇦", "KAZ": "🇰🇿", "EST": "🇪🇪",
    "SVN": "🇸🇮", "FRA": "🇫🇷", "LTU": "🇱🇹"
}

admin_no_cooldown = set()
# Был ли когда-либо админом
was_admin_before = set()
CARDS_PER_PAGE = 50

# --- Для обменов ---
pending_trades = {}
trade_confirmations = {}
# --- Для изменения статов карточек ---
admin_edit_state = {}


TRADE_NHL_PHRASES = [
    "Блокбастер трейд! 🚨",
    "Это обмен десятилетия! 🤯",
    "Вау, какая сделка! 🏒",
    "Сделка недели — аплодисменты менеджерам! 👏",
    "Настоящий обмен звёзд! 🌟",
    "Эти GM знают своё дело!",
    "Обмен, который войдёт в историю NHL! 📚",
    "Похоже, команда стала только сильнее!",
    "Главный трейд этой зимы! ❄️",
    "Шокирующий обмен! 🔥",
    "Молния в шапке! ⚡️",
    "Два лидера поменялись домами!",
    "Весь мир хоккея обсуждает этот обмен!",
    "В раздевалке — только разговоры об этой сделке!",
    "Контракты подписаны — обмен завершён!",
]

def get_db():
    return db.get_db()

def setup_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT, last_card_time INTEGER)')
    try:
        c.execute("ALTER TABLE users ADD COLUMN last_week_score INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN referrals_count INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN invited_by INTEGER DEFAULT NULL")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN xp INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN level INTEGER DEFAULT 1")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN xp_daily INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN last_xp_reset DATE")
        c.execute("UPDATE users SET last_xp_reset = DATE('now') WHERE last_xp_reset IS NULL")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN win_streak INTEGER DEFAULT 0")
    except Exception:
        pass
    # ... остальной код создания таблиц ...
    conn.commit()
    conn.close()
    load_card_cache(force=True)

def wrap_line(text, length=35):
    words = text.split()
    lines = []
    line = ''
    for word in words:
        if len(line) + len(word) + 1 <= length:
            line += (word + ' ')
        else:
            lines.append(line.strip())
            line = word + ' '
    if line:
        lines.append(line.strip())
    return "\n".join(lines)

def weighted_random_rarity():
    rarities = list(RARITY_WEIGHTS.keys())
    weights = list(RARITY_WEIGHTS.values())
    return random.choices(rarities, weights=weights, k=1)[0]

def pos_to_rus(pos):
    parts = [p.strip().upper() for p in pos.replace("\\", "/").split("/")]
    rus_parts = [POS_RU.get(p, p) for p in parts if p]
    return "/".join(rus_parts) if rus_parts else pos

def flag_from_iso3(iso):
    return ISO3_TO_FLAG.get((iso or "").upper(), "")

def _get_random_card_sync():
    conn = get_db()
    c = conn.cursor()
    rarity = weighted_random_rarity()
    c.execute(
        'SELECT * FROM cards WHERE rarity=? '
        "AND img NOT LIKE '%default-skater.png%' "
        "AND img NOT LIKE '%default-goalie.png%' "
        "AND img != '' AND img IS NOT NULL "
        'ORDER BY RANDOM() LIMIT 1',
        (rarity,)
    )
    row = c.fetchone()
    conn.close()
    if row:
        fields = ["id", "name", "img", "pos", "country", "born", "height", "weight", "rarity", "stats", "team_en", "team_ru"]
        return dict(zip(fields, row))
    return None

async def get_random_card(*args, **kwargs):
    return await asyncio.to_thread(_get_random_card_sync, *args, **kwargs)

def _get_user_cards_sync(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT card_id FROM inventory WHERE user_id=?", (user_id,))
    rows = [r[0] for r in c.fetchall()]
    conn.close()

    card_counts = Counter(rows)
    cards = []
    for card_id, count in card_counts.items():
        card = get_card_from_cache(card_id)
        if card:
            s = f"{card['name']} ({RARITY_RU.get(card['rarity'], card['rarity'])})"
            if count > 1:
                s += f" x{count}"
            cards.append(s)
    return cards

async def get_user_cards(*args, **kwargs):
    return await asyncio.to_thread(_get_user_cards_sync, *args, **kwargs)

async def send_ranking_push(user_id, context, chat_id):
    # теперь пушим всем (можно и админам)
    rank, total = await get_user_rank_cached(user_id)
    if rank > total:
        return
    if rank <= 5:
        msg = f"Ты уже в ТОП-5 — круто! Продолжай собирать и держись в лидерах! 🏒"
    else:
        top5 = await get_top_users(limit=5)
        user_score = await get_user_score_cached(user_id)
        if len(top5) == 5:
            score5 = int(top5[4][2])
            delta = int(score5 - user_score)
            need = delta + 1 if delta >= 0 else 0
        else:
            need = 0
        msg = f"Ты уже #{rank} из {total}! "
        if need > 0:
            msg += f"До топ-5 всего {need} очк{'а' if need%10 in [2,3,4] and need%100 not in [12,13,14] else 'ов'}, не сдавайся! 💪"
        else:
            msg += "Уже почти в топе!"
    await context.bot.send_message(chat_id, msg)


async def _send_rank_text(update: Update, text: str) -> None:
    """Send ranking text in response to a message or callback."""
    if getattr(update, "message", None):
        await update.message.reply_text(text)
        return
    if getattr(update, "callback_query", None):
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text)
        return

# ------- ОЧКИ и РЕЙТИНГИ -----------
def parse_points(stats, pos):
    if pos == "G":
        win = 0
        gaa = 3.0
        m_win = re.search(r'Поб\s+(\d+)', stats or "")
        m_gaa = re.search(r'КН\s*([\d.,]+)', stats or "")
        if m_win:
            win = int(m_win.group(1))
        if m_gaa:
            try:
                gaa = float(m_gaa.group(1).replace(",", "."))
            except ValueError:
                gaa = 3.0
        return win * 2 + (30 - gaa * 10)
    else:
        m = re.search(r'Очки\s+(\d+)', stats or "")
        return int(m.group(1)) if m else 0

def extract_points(stats: str | None) -> str:
    """Return points value from stats for field players as string."""
    m = re.search(r"Очки\s+(\d+)", stats or "")
    return m.group(1) if m else "0"

def extract_goalie_stats(stats: str | None) -> tuple[str, str]:
    """Return wins and GAA (КН) from goalie stats as strings."""
    m_win = re.search(r"Поб\s+(\d+)", stats or "")
    wins = m_win.group(1) if m_win else "0"
    m_kn = re.search(r"КН\s*([\d.,]+)", stats or "")
    kn = m_kn.group(1) if m_kn else "0"
    return wins, kn

def update_card_points(card_id: int) -> None:
    """Recalculate and store points value for a card."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT pos, stats FROM cards WHERE id=?", (card_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return
    pos, stats = row
    points = parse_points(stats, pos)
    cur.execute("UPDATE cards SET points=? WHERE id=?", (points, card_id))
    conn.commit()
    conn.close()
    refresh_card_cache(card_id)
    invalidate_score_cache_for_card(card_id)

def format_card_caption(
    card: dict,
    *,
    index: int = 0,
    total: int = 1,
    filter_name: str = "",
    total_cards: int | None = None,
    show_filter: bool = True,
) -> str:
    """Return formatted caption for a card."""
    pos = card.get("pos") or ""
    pos_ru = pos_to_rus(pos)
    flag = flag_from_iso3(card.get("country"))
    iso = (card.get("country") or "").upper()
    club = (card.get("team_ru") or card.get("team_en") or "—").strip()
    rarity = card.get("rarity", "common")
    rarity_ru = RARITY_RU_SHORT.get(rarity, rarity)
    rarity_emoji = RARITY_EMOJI.get(rarity, "")

    parts = [
        f"*{card.get('name','?')}*",
        f"_{rarity_emoji} {rarity_ru} карта_",
        "",
        f"*Клуб:* {club}",
        f"*Амплуа:* {'Вратарь' if pos == 'G' else pos_ru}",
        f"*Страна:* {flag} {iso}",
        "",
    ]

    stats = card.get("stats", "")
    if pos == "G":
        wins, kn = extract_goalie_stats(stats)
        parts.append(f"📊 *Победы:* {wins}")
        parts.append(f"*КН:* {kn}")
    else:
        pts = extract_points(stats)
        parts.append(f"📊 *Очки:* {pts}")
    parts.append("────────────")

    if show_filter:
        parts.append(f"[{index+1} из {total} | Фильтр: {filter_name}]")
    if total_cards is not None:
        parts.append(f"📦 Всего: {total_cards} карт")

    return "\n".join(filter(None, parts))

def _calculate_user_score_sync(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT card_id FROM inventory WHERE user_id=?", (user_id,))
    card_ids = [row[0] for row in c.fetchall()]
    conn.close()

    counts = Counter(card_ids)
    total_score = 0
    for card_id, count in counts.items():
        card = get_card_from_cache(card_id)
        if not card:
            continue
        pos = card["pos"]
        stats = card["stats"]
        rarity = card["rarity"]
        points = parse_points(stats, pos)
        mult = RARITY_MULTIPLIERS.get(rarity, 1)
        total_score += points * mult * count

    return total_score

async def calculate_user_score(*args, **kwargs):
    return await asyncio.to_thread(_calculate_user_score_sync, *args, **kwargs)

def get_user_score_cached_sync(user_id: int) -> float:
    cached = SCORE_CACHE.get(user_id)
    if cached and time.time() - cached[1] < SCORE_TTL:
        return cached[0]
    score = _calculate_user_score_sync(user_id)
    SCORE_CACHE[user_id] = (score, time.time())
    return score

async def get_user_score_cached(user_id: int) -> float:
    return await asyncio.to_thread(get_user_score_cached_sync, user_id)

def _get_user_rank_sync(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM users")
    # Исключаем админов из рейтинга
    user_ids = [row[0] for row in c.fetchall() if not is_admin(row[0])]
    scores = []
    for uid in user_ids:
        score = get_user_score_cached_sync(uid)
        scores.append((uid, score))
    scores.sort(key=lambda x: x[1], reverse=True)
    total = len(scores)
    for idx, (uid, _) in enumerate(scores):
        if uid == user_id:
            rank = idx + 1
            break
    else:
        rank = total
    conn.close()
    return rank, total

async def get_user_rank(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM users")
    user_ids = [row[0] for row in c.fetchall() if not is_admin(row[0])]
    conn.close()
    scores = await asyncio.gather(*[get_user_score_cached(uid) for uid in user_ids])
    pairs = list(zip(user_ids, scores))
    pairs.sort(key=lambda x: x[1], reverse=True)
    total = len(pairs)
    for idx, (uid, _) in enumerate(pairs):
        if uid == user_id:
            rank = idx + 1
            break
    else:
        rank = total
    return rank, total


async def get_user_rank_cached(user_id):
    cached = RANK_CACHE.get(user_id)
    if cached and time.time() - cached[2] < RANK_TTL:
        return cached[0], cached[1]
    rank, total = await get_user_rank(user_id)
    RANK_CACHE[user_id] = (rank, total, time.time())
    return rank, total

def get_weekly_progress(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT last_week_score FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    current = get_user_score_cached_sync(user_id)
    last = row[0] if row and row[0] is not None else 0
    return current - last

def _get_top_users_sync(limit=10):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, username, level FROM users")
    # Исключаем админов из топа
    users = [(uid, uname, lvl) for (uid, uname, lvl) in c.fetchall() if not is_admin(uid)]
    user_scores = []
    for uid, uname, lvl in users:
        score = get_user_score_cached_sync(uid)
        user_scores.append((uid, uname, score, lvl))
    user_scores.sort(key=lambda x: x[2], reverse=True)
    conn.close()
    return user_scores[:limit]

async def get_top_users(*args, **kwargs):
    limit = kwargs.get('limit', 10)
    data, ts = TOP_CACHE
    if data and time.time() - ts < TOP_TTL and len(data) >= limit:
        return data[:limit]
    result = await asyncio.to_thread(_get_top_users_sync, limit)
    globals()['TOP_CACHE'] = (result, time.time())
    return result

# ------- КОМАНДЫ РЕЙТИНГА ----------
@require_subscribe
async def me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_admin(user_id):
        await update.message.reply_text("У админов нет профиля в рейтинге.")
        return
    rank, total = await get_user_rank_cached(user_id)
    progress = round(get_weekly_progress(user_id))
    score = await get_user_score_cached(user_id)
    xp, lvl = db.get_xp_level(user_id)
    to_next = xp_to_next(xp)
    unique_cnt, total_cnt = get_inventory_counts(user_id)
    streak = db.get_win_streak(user_id)
    style, tagline = get_player_style(lvl, progress, streak)

    text = (
        "👤 *Твой профиль*\n\n"
        f"🔥 Очки: *{int(score)}*\n"
        f"🏆 Рейтинг: *#{rank} из {total}*\n"
        f"⚡️ Прирост: *+{progress} очк* — красавчик!\n\n"
        f"🔼 Уровень: *{lvl}*\n"
        f"📈 До Lv↑: *{to_next} XP*\n\n"
        f"📦 Карт: *{total_cnt}* (уникальных: *{unique_cnt}*)\n"
        f"🎖️ В ТОП-10 коллекционеров!\n\n"
        f"👥 Приглашено: *{get_referral_count(user_id)}*\n\n"
        f"🎯 *Твой стиль:* {style}\n"
        f"🧠 *{tagline}*"
    )
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⚙ Управление командой", callback_data="open_team")],
                [InlineKeyboardButton("📜 Посмотреть историю боёв", callback_data="menu_history")],
            ]
        ),
    )

@require_subscribe
async def xp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    xp, lvl = db.get_xp_level(uid)
    cap = 150 * (lvl ** 2)
    bar_fill = int(10 * xp / cap)
    bar = '▓' * bar_fill + '░' * (10 - bar_fill)
    await update.message.reply_text(
        f"📈 Lv {lvl} {bar}  {xp}/{cap} XP"
    )

@require_subscribe
async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, username, level FROM users")
    rows = [(u, n, l) for u, n, l in c.fetchall() if not is_admin(u)]
    conn.close()

    scores = await asyncio.gather(*[get_user_score_cached(u) for u, _, _ in rows])
    pairs = [(u, n, s, l) for (u, n, l), s in zip(rows, scores)]
    pairs.sort(key=lambda x: x[2], reverse=True)

    lines = ["🏆 ТОП по очкам:", ""]
    for i, (uid, uname, score, lvl) in enumerate(pairs[:10], 1):
        name = f"@{uname}" if uname else f"ID:{uid}"
        lines.append(f"{i}. {name}")
        lines.append(f"🔥 {shorten_number(int(score))} очков  🔼 {lvl} ур.")
        lines.append("")

    user_id = update.effective_user.id
    total = len(pairs)
    rank = next((idx + 1 for idx, (u, _, _, _) in enumerate(pairs) if u == user_id), total)
    score = int(await get_user_score_cached(user_id))
    _, lvl = db.get_xp_level(user_id)
    lines.append(f"👀 Ты — #{rank} из {total}")
    lines.append(f"🔥 {shorten_number(score)} очков  🔼 {lvl} ур.")
    if rank > 1:
        diff = int(pairs[rank-2][2] - score)
        lines.append(f"🚀 До следующего места: {shorten_number(diff)} очков")

    text = "\n".join(lines).rstrip()
    await _send_rank_text(update, text)


@require_subscribe
async def open_team(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open team management via callback."""
    await _call_with_query_message(handlers.create_team, update, context)

@require_subscribe


@admin_only
async def resetweek(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    record_admin_usage(user_id, "/resetweek")
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM users")
    users = c.fetchall()
    for (uid,) in users:
        score = await get_user_score_cached(uid)
        c.execute("UPDATE users SET last_week_score=? WHERE id=?", (score, uid))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ Еженедельные приросты обновлены для всех игроков.")

# -------- start с проверкой на админа ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or ""

    # --- Проверка подписки ---
    if not await is_user_subscribed(context.bot, user_id):
        buttons = [
            [InlineKeyboardButton(f"🔔 {ch['name']}", url=ch['link'])] for ch in CHANNELS
        ]
        buttons.append([InlineKeyboardButton("✅ Проверить подписку", callback_data="check_subscribe")])

        text = (
            "🏒 *Доступ к боту только для подписчиков!*\n\n"
            "Чтобы начать, подпишись на оба канала:\n" +
            "\n".join([f"• [{ch['name']}]({ch['link']})" for ch in CHANNELS]) +
            "\n\n"
            "Зачем это?\n"
            "— Только участники получают эксклюзивные карточки, трейды и призы\n"
            "— Новости, конкурсы, общение\n"
            "1. Подпишись на оба канала\n"
            "2. Жми 'Проверить подписку'"
        )
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        return

    # --- Всё что ниже — ОБЯЗАТЕЛЬНО внутри функции! ---
    conn = get_db()
    c = conn.cursor()
    c.execute(
        (
            "INSERT INTO users (id, username, last_card_time, invited_by, referrals_count) "
            "VALUES (?, ?, 0, NULL, 0) ON CONFLICT (id) DO NOTHING"
        ),
        (user_id, username),
    )

    # --- Обработка реферала ---
    if context.args and context.args[0].isdigit():
        referrer_id = int(context.args[0])
        if referrer_id != user_id:  # нельзя самому себя приглашать
            c.execute("SELECT invited_by FROM users WHERE id=?", (user_id,))
            row = c.fetchone()
            # если впервые приходит по ссылке
            if not row or not row[0]:
                c.execute("UPDATE users SET invited_by=? WHERE id=?", (referrer_id, user_id))
                c.execute("UPDATE users SET referrals_count=referrals_count+1 WHERE id=?", (referrer_id,))
                # СБРАСЫВАЕМ КУЛДАУН пригласившему
                c.execute("UPDATE users SET last_card_time=0 WHERE id=?", (referrer_id,))
                conn.commit()
                try:
                    await context.bot.send_message(
                        referrer_id,
                        "🎉 По твоей ссылке зашёл новый игрок!\n\n"
                        "⏳ Твой кулдаун на карточку сброшен. Можешь открыть новую прямо сейчас! Приглашай друзей и собирай коллекцию быстрее."
                    )
                except Exception:
                    pass

    # --- Обычное приветствие и закрытие базы ---
    conn.commit()
    conn.close()
    await send_main_menu(update, context)

@require_subscribe
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show main menu. Same as /start."""
    await send_main_menu(update, context)

@require_subscribe
async def card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in banned_users:
        await update.message.reply_text("🚫 Вы заблокированы в боте.")
        return
    now = int(time.time())
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT last_card_time FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    last = row[0] if row else 0
    if user_id not in admin_no_cooldown:
        if now - last < CARD_COOLDOWN:
            mins = (CARD_COOLDOWN - (now - last)) // 60
            await update.message.reply_text(
                f"⏳ Следующую карточку можно получить через {mins} мин.\n"
                "💡 Если твой друг зайдёт по твоей ссылке из /invite, кулдаун сбросится сразу!"
            )
            conn.close()
            return
    card_obj = await get_random_card()
    if not card_obj:
        await update.message.reply_text("В базе нет карточек с фото или данного раритета.")
        conn.close()
        return
    c.execute("INSERT INTO inventory (user_id, card_id, time_got) VALUES (?, ?, ?)", (user_id, card_obj["id"], now))
    c.execute("UPDATE users SET last_card_time=? WHERE id=?", (now, user_id))
    conn.commit()
    conn.close()

    _, total_cards = get_inventory_counts(user_id)
    caption = format_card_caption(
        card_obj,
        total_cards=total_cards,
        show_filter=False,
    )

    try:
        await context.bot.send_photo(update.message.chat_id, card_obj.get('img', ''), caption=caption, parse_mode='Markdown')
    except BadRequest:
        await update.message.reply_text(
            f"⚠️ Картинка карточки недоступна, но вот информация:\n{caption}",
            parse_mode='Markdown'
        )

    context.application.create_task(
        send_ranking_push(user_id, context, update.message.chat_id)
    )

    await update.message.reply_text(
        "✨ Что дальше?",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🏠 Вернуться в меню", callback_data="menu_back")]]
        ),
    )

# --- TRADE (ОБМЕНЫ) ---

def make_card_button(card_id, name, rarity, count):
    rarity_emoji = {
        "legendary": "⭐️",
        "mythic": "🟥",
        "epic": "💎",
        "rare": "🔵",
        "common": "🟢"
    }.get(rarity, "🟢")
    count_str = f"x{count}" if count > 1 else ""
    special = ""
    if rarity == "legendary":
        special = " 🏆"
    elif rarity == "epic":
        special = " 🥈"
    elif rarity == "mythic":
        special = " 🔥"
    text = f"{rarity_emoji} {name} {count_str}{special}"
    return InlineKeyboardButton(text, callback_data=f"trade_offer_{card_id}")

async def show_trade_cards(context, user_id, prompt):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT card_id, COUNT(*) FROM inventory WHERE user_id=? GROUP BY card_id", (user_id,))
    cards = c.fetchall()
    conn.close()
    if not cards:
        await context.bot.send_message(user_id, "У тебя нет карточек для обмена.")
        pending_trades.pop(user_id, None)
        return
    buttons = []
    for card_id, count in cards:
        card = get_card_from_cache(card_id)
        if not card:
            continue  # если карты нет в базе — не выводим
        name = card["name"]
        rarity = card["rarity"]
        btn = [make_card_button(card_id, name, rarity, count)]
        buttons.append(btn)
    if not buttons:
        await context.bot.send_message(user_id, "Нет доступных карт для обмена.")
        pending_trades.pop(user_id, None)
        return
    markup = InlineKeyboardMarkup(buttons)
    await context.bot.send_message(user_id, prompt, reply_markup=markup)

async def show_trade_selector(context, user_id, prompt, is_acceptor=False, page=0, edit_message_id=None):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT card_id FROM inventory WHERE user_id=?", (user_id,))
    card_ids = [r[0] for r in c.fetchall()]
    count_dict = Counter(card_ids)
    conn.close()

    if not card_ids:
        await context.bot.send_message(user_id, "У тебя нет карточек для обмена.")
        pending_trades.pop(user_id, None)
        return

    trade_state = pending_trades[user_id]
    selected = trade_state.get('selected', set())
    trade_state['page'] = page

    card_items = list(count_dict.items())
    card_items.sort()

    # Пагинация
    total_pages = (len(card_items) + TRADE_CARDS_PER_PAGE - 1) // TRADE_CARDS_PER_PAGE
    start = page * TRADE_CARDS_PER_PAGE
    end = start + TRADE_CARDS_PER_PAGE
    page_cards = card_items[start:end]

    buttons = []
    for card_id, count in page_cards:
        card_name, rarity = get_card_name_rarity(card_id)
        if card_name == "?":
            continue  # не показываем битые карты!
        checked = "✅ " if card_id in selected else ""
        btn = InlineKeyboardButton(
            f"{checked}{card_name} ({RARITY_RU.get(rarity, rarity)})",
            callback_data=f"trade_select_{card_id}"
        )
        buttons.append([btn])

    controls = []
    if selected:
        controls.append(InlineKeyboardButton("Готово", callback_data="trade_confirm"))
    controls.append(InlineKeyboardButton("Отмена", callback_data="trade_cancel"))

    # Навигация
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Назад", callback_data="trade_page_prev"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Вперёд ▶️", callback_data="trade_page_next"))

    markup_list = []
    if nav_buttons:
        markup_list.append(nav_buttons)
    markup_list += buttons
    markup_list.append(controls)
    markup = InlineKeyboardMarkup(markup_list)

    if edit_message_id:
        await context.bot.edit_message_reply_markup(
            chat_id=user_id,
            message_id=edit_message_id,
            reply_markup=markup
        )
    else:
        await context.bot.send_message(user_id, prompt, reply_markup=markup)


# --- MULTI TRADE ---

@require_subscribe
async def trade_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show instructions for starting a trade."""
    user_id = update.effective_user.id
    text = (
        "🔄 *Обмен картами*\n\n"
        "Команда для обмена: `/trade <user_id>`\n"
        f"Твой ID: `{user_id}`\n\n"
        "Отправь этот ID другу, чтобы начать трейд!"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

MAX_TRADE_CARDS = 5
TRADE_CARDS_PER_PAGE = 20

@require_subscribe
async def trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Используй: /trade <user_id>\nПример: /trade 123456789")
        return
    partner_id = int(context.args[0])
    if partner_id == user_id:
        await update.message.reply_text("Нельзя обмениваться с собой!")
        return

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE id=?", (partner_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        await update.message.reply_text("Пользователь не найден.")
        return

    pending_trades[user_id] = {
        'partner_id': partner_id,
        'stage': 'initiator_selecting',
        'selected': set()
    }
    pending_trades[partner_id] = {
        'partner_id': user_id,
        'stage': 'accept_offer'
    }
    await show_trade_selector(context, user_id, "Выбери до 5 своих карточек для обмена (можно несколько):")

async def trade_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if user_id not in pending_trades:
        await query.answer("Нет активного обмена.")
        return
    trade_state = pending_trades[user_id]
    page = trade_state.get('page', 0)
    if query.data == "trade_page_prev":
        page = max(0, page - 1)
    elif query.data == "trade_page_next":
        page = page + 1
    try:
        await query.answer()
    except BadRequest:
        return
    await show_trade_selector(
        context, user_id,
        "Выбери до 5 своих карточек для обмена (можно несколько):",
        page=page,
        edit_message_id=query.message.message_id
    )

async def trade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if user_id not in pending_trades:
        await query.answer("Нет активного обмена.")
        return

    trade_state = pending_trades[user_id]
    stage = trade_state['stage']
    partner_id = trade_state['partner_id']
    data = query.data

    # Пагинация при выборе
    if data == "trade_page_prev" or data == "trade_page_next":
        page = trade_state.get('page', 0)
        if data == "trade_page_prev":
            page = max(0, page - 1)
        else:
            page = page + 1
        await show_trade_selector(
            context, user_id,
            "Выбери до 5 своих карточек для обмена (можно несколько):",
            page=page,
            edit_message_id=query.message.message_id
        )
        try:
            await query.answer()
        except BadRequest:
            pass
        return

    # Выбор карточки
    if data.startswith("trade_select_"):
        card_id = int(data.split("_")[2])
        sel = trade_state.get('selected', set())
        if card_id in sel:
            sel.remove(card_id)
        else:
            if len(sel) >= MAX_TRADE_CARDS:
                await query.answer(f"Можно выбрать не более {MAX_TRADE_CARDS} карт.")
                return
            sel.add(card_id)
        trade_state['selected'] = sel
        await show_trade_selector(
            context, user_id,
            "Выбери до 5 своих карточек для обмена (можно несколько):",
            page=trade_state.get('page', 0),
            edit_message_id=query.message.message_id
        )
        try:
            await query.answer()
        except BadRequest:
            pass
        return

    # Завершение выбора инициатором — второму игроку показывается предложение с кнопками
    if data == "trade_confirm":
        if stage == "initiator_selecting":
            if not trade_state.get('selected'):
                await query.answer("Выбери хотя бы одну карту для обмена.")
                return
            pending_trades[user_id]['stage'] = 'waiting_accept'
            pending_trades[partner_id] = {
                'partner_id': user_id,
                'stage': 'accept_offer',
                'offer': set(trade_state['selected'])
            }
            card_names = [get_card_name_rarity(cid)[0] for cid in trade_state['selected']]
            text = (
                f"Тебе предлагают обмен на эти карты:\n"
                f"{', '.join(card_names)}\n\n"
                "Принять обмен?"
            )
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("Принять", callback_data="trade_accept_offer")],
                [InlineKeyboardButton("Отклонить", callback_data="trade_reject_offer")]
            ])
            await context.bot.send_message(partner_id, text, reply_markup=markup)
            await query.edit_message_text("Ожидание решения второго участника...")
            return

        elif stage == "acceptor_selecting":
            if not trade_state.get('selected'):
                await query.answer("Выбери хотя бы одну карту для обмена.")
                return
            offer1 = set(trade_state['offer'])
            offer2 = set(trade_state['selected'])
            # Сохраняем инфу для финального подтверждения
            trade_confirmations[(user_id, partner_id)] = {
                "initiator": partner_id,
                "acceptor": user_id,
                "offer1": offer1,
                "offer2": offer2,
                "confirmed": set()
            }
            await show_trade_confirmation(context, partner_id, user_id, offer1, offer2)
            await show_trade_confirmation(context, user_id, partner_id, offer1, offer2)
            await query.edit_message_text("Ожидание подтверждения обмена обоими игроками.")
            return

    # Второй игрок соглашается — ему показывается выбор своих карт (правильная обработка!)
    if data == "trade_accept_offer":
        trade_state['stage'] = 'acceptor_selecting'
        trade_state['selected'] = set()
        await show_trade_selector(
            context, user_id,
            "Выбери до 5 своих карточек для обмена (можно несколько):",
            is_acceptor=True,
            page=0,
            edit_message_id=query.message.message_id
        )
        return

    # Второй игрок отклоняет — обмен отменяется у обоих
    if data == "trade_reject_offer":
        await context.bot.send_message(user_id, "Ты отклонил обмен.")
        await context.bot.send_message(partner_id, "Твой обмен был отклонён.")
        pending_trades.pop(user_id, None)
        pending_trades.pop(partner_id, None)
        try:
            await query.edit_message_text("Обмен отклонён.")
        except:
            pass
        return

    # Отмена обмена
    if data == "trade_cancel":
        await context.bot.send_message(user_id, "Обмен отменён.")
        await context.bot.send_message(partner_id, "Обмен отменён второй стороной.")
        pending_trades.pop(user_id, None)
        pending_trades.pop(partner_id, None)
        try:
            await query.edit_message_text("Обмен отменён.")
        except:
            pass
        return

    # Финальное подтверждение обмена
    if data == "trade_final_confirm":
        # Найти трейд
        found = None
        for k in trade_confirmations.keys():
            if user_id in k:
                found = k
                break
        if not found:
            await query.answer("Нет ожидающего подтверждения обмена.")
            return
        trade_confirmations[found]["confirmed"].add(user_id)
        if len(trade_confirmations[found]["confirmed"]) == 2:
            vals = trade_confirmations.pop(found)
            await finalize_multi_trade(
                context,
                vals["acceptor"],  # второй игрок
                vals["initiator"], # первый игрок
                vals["offer1"],
                vals["offer2"]
            )
        else:
            await query.edit_message_text("Ожидаем подтверждение второго участника...")
        return

    if data == "trade_final_cancel":
        found = None
        for k in trade_confirmations.keys():
            if user_id in k:
                found = k
                break
        if not found:
            await query.answer("Нет ожидающего подтверждения обмена.")
            return
        vals = trade_confirmations.pop(found)
        await context.bot.send_message(vals["initiator"], "Обмен отменён одним из участников.")
        await context.bot.send_message(vals["acceptor"], "Обмен отменён одним из участников.")
        pending_trades.pop(vals["initiator"], None)
        pending_trades.pop(vals["acceptor"], None)
        await query.edit_message_text("Обмен отменён.")
        return

    await query.answer("Неизвестное действие.")

async def show_trade_confirmation(context, uid, other_uid, offer1, offer2):
    # Кто ты: инициатор или акцептор
    if uid == other_uid:
        return
    role = "initiator" if uid != other_uid else "acceptor"
    my_give = offer1 if uid != other_uid else offer2
    my_get  = offer2 if uid != other_uid else offer1

    def cards_to_str(cards):
        out = []
        for cid in cards:
            name, rarity = get_card_name_rarity(cid)
            out.append(f"{name} ({RARITY_RU.get(rarity, rarity)})")
        return ", ".join(out) if out else "—"

    give_names = cards_to_str(my_give)
    get_names  = cards_to_str(my_get)

    text = (
        "Проверь детали обмена:\n\n"
        f"Ты отдаёшь: {give_names}\n"
        f"Ты получаешь: {get_names}\n\n"
        "Подтверди обмен!"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить", callback_data="trade_final_confirm")],
        [InlineKeyboardButton("❌ Отменить", callback_data="trade_final_cancel")]
    ])
    await context.bot.send_message(uid, text, reply_markup=markup)

async def finalize_multi_trade(context, acceptor_id, initiator_id, offer1, offer2):
    # offer1 — карты инициатора, offer2 — карты acceptor
    for cid in offer1:
        remove_card(initiator_id, cid)
        add_card(acceptor_id, cid)
    for cid in offer2:
        remove_card(acceptor_id, cid)
        add_card(initiator_id, cid)

    offer1_names = [get_card_name_rarity(cid)[0] for cid in offer1]
    offer2_names = [get_card_name_rarity(cid)[0] for cid in offer2]
    nhl_phrase = random.choice(TRADE_NHL_PHRASES)

    await context.bot.send_message(
        initiator_id,
        f"{nhl_phrase}\n\n"
        f"Ты обменялся!\n"
        f"Отдал: {', '.join(offer1_names)}\n"
        f"Получил: {', '.join(offer2_names)}"
    )
    await context.bot.send_message(
        acceptor_id,
        f"{nhl_phrase}\n\n"
        f"Ты обменялся!\n"
        f"Отдал: {', '.join(offer2_names)}\n"
        f"Получил: {', '.join(offer1_names)}"
    )
    for uid in (initiator_id, acceptor_id):
        await context.bot.send_message(
            uid,
            "🎯 Готов к следующему шагу?",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Вернуться в меню", callback_data="menu_back")]]),
        )
    pending_trades.pop(initiator_id, None)
    pending_trades.pop(acceptor_id, None)

def get_card_name_rarity(card_id):
    card = get_card_from_cache(card_id)
    if card:
        return card["name"], card["rarity"]
    return "?", "common"

def get_rarity_emoji(rarity):
    return {
        "legendary": "⭐️",
        "mythic": "🟥",
        "epic": "💎",
        "rare": "🔵",
        "common": "🟢"
    }.get(rarity, "🟢")

def remove_card(user_id, card_id):
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute(
            "DELETE FROM inventory WHERE ctid IN (SELECT ctid FROM inventory WHERE user_id=? AND card_id=? LIMIT 1)",
            (user_id, card_id),
        )
    except Exception:
        c.execute(
            "DELETE FROM inventory WHERE user_id=? AND card_id=? LIMIT 1",
            (user_id, card_id),
        )
    conn.commit()
    conn.close()

def add_card(user_id, card_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO inventory (user_id, card_id, time_got) VALUES (?, ?, ?)", (user_id, card_id, int(time.time())))
    conn.commit()
    conn.close()

def get_full_cards_for_user(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT card_id FROM inventory WHERE user_id=?", (user_id,))
    ids = [r[0] for r in c.fetchall()]
    conn.close()

    count_dict = Counter(ids)
    cards = []
    total_count = 0
    for cid, cnt in count_dict.items():
        card = get_card_from_cache(cid)
        if not card:
            continue
        card_copy = card.copy()
        card_copy["count"] = cnt
        cards.append(card_copy)
        total_count += cnt

    return cards, total_count

def get_inventory_counts(user_id):
    """Return number of unique cards and total copies for user."""
    cards, total = get_full_cards_for_user(user_id)
    return len(cards), total

def get_all_club_keys():
    """Return sorted list of all club keys from team_en or team_ru."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """
        SELECT DISTINCT COALESCE(team_en, team_ru) AS club
          FROM cards
         WHERE COALESCE(team_en, team_ru) IS NOT NULL
           AND COALESCE(team_en, team_ru) != ''
        """
    )
    clubs = sorted(r[0] for r in c.fetchall())
    conn.close()
    return clubs


def get_club_total_counts():
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """
        SELECT COALESCE(team_en, team_ru) AS club,
               COUNT(DISTINCT id)
          FROM cards
         WHERE COALESCE(team_en, team_ru) IS NOT NULL
           AND COALESCE(team_en, team_ru) != ''
      GROUP BY COALESCE(team_en, team_ru)
        """
    )
    data = {row[0]: row[1] for row in c.fetchall()}
    conn.close()
    return data


def get_user_club_counts(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """
        SELECT COALESCE(cards.team_en, cards.team_ru) AS club,
               COUNT(DISTINCT cards.id)
          FROM inventory
          JOIN cards ON inventory.card_id = cards.id
         WHERE inventory.user_id = ?
           AND COALESCE(cards.team_en, cards.team_ru) IS NOT NULL
           AND COALESCE(cards.team_en, cards.team_ru) != ''
      GROUP BY COALESCE(cards.team_en, cards.team_ru)
        """,
        (user_id,)
    )
    data = {row[0]: row[1] for row in c.fetchall()}
    conn.close()
    return data


def get_user_club_cards(user_id, club_key):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """
        SELECT cards.id
          FROM inventory
          JOIN cards ON inventory.card_id = cards.id
         WHERE inventory.user_id = ?
           AND COALESCE(cards.team_en, cards.team_ru) = ?
        """,
        (user_id, club_key),
    )
    ids = [r[0] for r in c.fetchall()]
    conn.close()

    count_dict = Counter(ids)
    cards = []
    for cid, cnt in count_dict.items():
        card = get_card_from_cache(cid)
        if not card:
            continue
        card_copy = card.copy()
        card_copy["count"] = cnt
        cards.append(card_copy)
    return cards, sum(count_dict.values())

def get_team_cards(user_id):
    """Return list of card dicts from user's saved team."""
    team = db.get_team(user_id)
    if not team:
        return [], 0
    ids = team.get("lineup", []) + team.get("bench", [])
    cards = []
    for cid in ids:
        card = get_card_from_cache(cid)
        if card:
            cpy = card.copy()
            cpy["count"] = 1
            cards.append(cpy)
    return cards, len(cards)

def fetch_user_cards(user_id, rarity=None, club=None, new_only=False):
    conn = get_db()
    c = conn.cursor()
    query = (
        "SELECT cards.id, cards.name, cards.rarity, COUNT(*) as cnt "
        "FROM inventory JOIN cards ON inventory.card_id = cards.id "
        "WHERE inventory.user_id=?"
    )
    params = [user_id]
    if rarity:
        query += " AND cards.rarity=?"
        params.append(rarity)
    if club:
        query += " AND COALESCE(cards.team_en, cards.team_ru)=?"
        params.append(club)
    if new_only:
        query += " AND inventory.time_got >= ?"
        params.append(int(time.time()) - 86400)
    query += " GROUP BY cards.id, cards.name, cards.rarity"
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return rows

def build_filtered_cards(user_id, *, rarity=None, club=None, new_only=False, duplicates=False):
    """Return a sorted list of card dicts with count."""
    rows = fetch_user_cards(user_id, rarity=rarity, club=club, new_only=new_only)
    if duplicates:
        rows = [r for r in rows if r[3] > 1]
    cards = []
    for cid, name, rar, cnt in rows:
        card = get_card_from_cache(cid)
        if not card:
            continue
        cpy = card.copy()
        cpy["count"] = cnt
        cards.append(cpy)
    cards.sort(key=lambda c: (RARITY_ORDER.get(c.get("rarity", "common"), 99), c.get("name", "")))
    return cards

async def send_card_page(chat_id, context, cards, index=0, *, user_id=None, edit=False, message_id=None):
    """Send or edit a single card with navigation buttons."""
    if not cards:
        await context.bot.send_message(chat_id, "У тебя нет карточек по этому фильтру.")
        return
    index = max(0, min(index, len(cards) - 1))
    card = cards[index]
    # progress info
    state = context.user_data.get("coll", {})
    if state.get("rarity"):
        filter_name = f"{RARITY_RU_SHORT.get(state['rarity'], state['rarity'])}"
    elif state.get("club"):
        filter_name = state["club"]
    elif state.get("duplicates"):
        filter_name = "Повторки"
    elif state.get("new_only"):
        filter_name = "Новые"
    elif state.get("team"):
        filter_name = "В команде"
    else:
        filter_name = "Все"
    total_cards = None
    if user_id:
        _, total_cards = get_inventory_counts(user_id)
    caption = format_card_caption(
        card,
        index=index,
        total=len(cards),
        filter_name=filter_name,
        total_cards=total_cards,
        show_filter=True,
    )

    nav = []
    if index > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data="coll_prev"))
    if index < len(cards) - 1:
        nav.append(InlineKeyboardButton("➡️", callback_data="coll_next"))
    rows = []
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data="coll_back")])
    markup = InlineKeyboardMarkup(rows)

    try:
        if edit and message_id:
            await context.bot.edit_message_media(
                chat_id=chat_id,
                message_id=message_id,
                media=InputMediaPhoto(card.get("img", ""), caption=caption, parse_mode="Markdown"),
                reply_markup=markup,
            )
        else:
            await context.bot.send_photo(
                chat_id,
                card.get("img", ""),
                caption=caption,
                parse_mode="Markdown",
                reply_markup=markup,
            )
    except BadRequest:
        if edit and message_id:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=caption,
                reply_markup=markup,
                parse_mode="Markdown",
            )
        else:
            await context.bot.send_message(chat_id, caption, reply_markup=markup, parse_mode="Markdown")

async def send_collection_page(
    chat_id,
    user_id,
    context,
    page=0,
    *,
    rarity=None,
    club=None,
    new_only=False,
    duplicates=False,
    edit_message=False,
    message_id=None,
):
    rows = fetch_user_cards(user_id, rarity=rarity, club=club, new_only=new_only)
    if duplicates:
        rows = [r for r in rows if r[3] > 1]

    card_info = []
    for cid, name, rar, cnt in rows:
        idx = RARITY_ORDER.get(rar, 99)
        card_info.append((idx, name, cid, cnt, rar))

    if not card_info:
        await context.bot.send_message(chat_id, "У тебя нет карточек по этому фильтру.")
        return

    card_info.sort(key=lambda x: (x[0], x[1]))
    start = page * CARDS_PER_PAGE
    end = start + CARDS_PER_PAGE
    page_cards = card_info[start:end]
    if not page_cards:
        await context.bot.send_message(chat_id, "На этой странице нет карточек.")
        return

    grouped = {}
    for _, name, cid, count, rar in page_cards:
        grouped.setdefault(rar, []).append((name, count))

    lines = []
    for rar in ["legendary", "mythic", "epic", "rare", "common"]:
        items = grouped.get(rar)
        if not items:
            continue
        lines.append(f"{RARITY_EMOJI.get(rar,'')} {RARITY_RU_PLURAL[rar]}:")
        for name, count in items:
            suffix = f" x{count}" if count > 1 else ""
            lines.append(f"• {name}{suffix}")
        lines.append("")

    total_cards = sum(r[3] for r in card_info)
    unique_total = len(card_info)
    total_pages = (len(card_info) + CARDS_PER_PAGE - 1) // CARDS_PER_PAGE

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Назад", callback_data="coll_prev"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Вперёд ▶️", callback_data="coll_next"))

    rows = []
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("🔙 В коллекцию", callback_data="coll_back")])
    markup = InlineKeyboardMarkup(rows)

    title = "📦 Все карточки"
    if rarity:
        title = f"{RARITY_EMOJI.get(rarity, '')} {RARITY_RU_SHORT.get(rarity, rarity)}"
    elif club:
        title = f"🏒 {club}"
    elif duplicates:
        title = "♻️ Повторки"
    elif new_only:
        title = "🆕 Новые карточки"

    text = (
        f"{title} (стр. {page+1} из {total_pages}):\n\n" + "\n".join(lines).rstrip()
        + f"\n\nВсего у тебя: {total_cards} карточек (уникальных: {unique_total})"
    )

    if edit_message and message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=markup,
            )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                pass
            else:
                await context.bot.send_message(chat_id, text, reply_markup=markup)
    else:
        await context.bot.send_message(chat_id, text, reply_markup=markup)

def get_referral_count(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT referrals_count FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def get_ref_achievement(count: int) -> str:
    """Return single-line achievement label for given referral count."""
    if count >= 20:
        return "🏆 Легенда"
    if count >= 10:
        return "🥈 Капитан"
    if count >= 5:
        return "🥉 Маленькая команда"
    return ""

def get_referral_achievements(count):
    out = []
    if count >= 3:
        out.append("🥉 3 приглашённых — Первый друг")
    if count >= 5:
        out.append("🥈 5 приглашённых — Маленькая команда")
    if count >= 10:
        out.append("🏅 10 приглашённых — Лидер двора")
    if count >= 20:
        out.append("🥇 20 приглашённых — Легенда NHL")
    if count >= 50:
        out.append("🏆 50 приглашённых — Вдохновитель толпы")
    return "\n".join(out) if out else "— Пока нет ачивок"

async def invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    link = f"https://t.me/{context.bot.username}?start={user_id}"
    referrals = get_referral_count(user_id)
    achv = get_referral_achievements(referrals)
    text = (
        "🤝 Пригласи друга и получи ачивки!\n"
        "‼️ Когда друг заходит по твоей ссылке и запускает бота — твой кулдаун на карточку СРАЗУ СБРАСЫВАЕТСЯ!\n\n"
        f"Твоя ссылка: {link}\n\n"
        f"Уже приглашено: {referrals}\n"
        f"{achv}"
    )
    btn = InlineKeyboardButton("Пригласить друга", url=link)
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup([[btn]]))


async def topref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT id, username, referrals_count, level FROM users ORDER BY referrals_count DESC"
    )
    rows = [(uid, uname, cnt, lvl) for uid, uname, cnt, lvl in c.fetchall() if not is_admin(uid)]
    conn.close()
    if not rows:
        await _send_rank_text(update, "Пока никто не приглашал друзей.")
        return

    lines = ["🫂 ТОП по приглашениям:", ""]
    for i, (uid, username, count, lvl) in enumerate(rows[:10], 1):
        name = f"@{username}" if username else f"ID:{uid}"
        lines.append(f"{i}. {name}")
        lines.append(f"🫂 {count}  🔼 {lvl} ур.")
        lines.append("")

    user_id = update.effective_user.id
    total = len(rows)
    idx = next((j for j,(uid,_,_,_) in enumerate(rows) if uid == user_id), total-1)
    rank = idx + 1
    my_cnt = rows[idx][2] if idx < len(rows) else 0
    _, my_lvl = db.get_xp_level(user_id)
    lines.append(f"👀 Ты — #{rank} из {total}")
    lines.append(f"🫂 {my_cnt}  🔼 {my_lvl} ур.")
    if rank > 1:
        diff = rows[rank-2][2] - my_cnt
        lines.append(f"🚀 До следующего места: {diff} приглаш.")

    text = "\n".join(lines).rstrip()
    await _send_rank_text(update, text)


@require_subscribe
async def topweek(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, username, level FROM users")
    rows = [(uid, uname, lvl) for uid, uname, lvl in c.fetchall() if not is_admin(uid)]
    conn.close()

    progress_list = []
    for uid, uname, lvl in rows:
        prog = get_weekly_progress(uid)
        progress_list.append((uid, uname, prog, lvl))
    progress_list.sort(key=lambda x: x[2], reverse=True)

    lines = ["⚡️ Прирост за неделю:", ""]
    for i, (uid, uname, prog, lvl) in enumerate(progress_list[:10], 1):
        name = f"@{uname}" if uname else f"ID:{uid}"
        lines.append(f"{i}. {name}")
        lines.append(f"⚡️ +{shorten_number(int(prog))}  🔼 {lvl} ур.")
        lines.append("")

    user_id = update.effective_user.id
    my_prog = get_weekly_progress(user_id)
    total = len(progress_list)
    rank = next((idx + 1 for idx, (uid, *_ ) in enumerate(progress_list) if uid == user_id), total)
    _, my_lvl = db.get_xp_level(user_id)
    lines.append(f"👀 Ты — #{rank} из {total}")
    lines.append(f"⚡️ +{shorten_number(int(my_prog))}  🔼 {my_lvl} ур.")
    if rank > 1:
        diff = int(progress_list[rank-2][2] - my_prog)
        lines.append(f"🚀 До следующего места: {shorten_number(diff)} очков")

    text = "\n".join(lines).rstrip()
    await _send_rank_text(update, text)


@require_subscribe
async def topxp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    if ADMINS:
        placeholders = ','.join('?' for _ in ADMINS)
        query = f"SELECT id, username, level, xp FROM users WHERE id NOT IN ({placeholders}) ORDER BY level DESC, xp DESC"
        c.execute(query, tuple(ADMINS))
    else:
        query = "SELECT id, username, level, xp FROM users ORDER BY level DESC, xp DESC"
        c.execute(query)
    rows = [
        (
            uid,
            uname,
            lvl if lvl is not None else 1,
            xp if xp is not None else 0,
        )
        for uid, uname, lvl, xp in c.fetchall()
    ]
    # В некоторых инсталляциях порядок из БД может быть некорректным.
    # Отсортируем ещё раз в Python по уровню и XP по убыванию.
    rows.sort(key=lambda r: (r[2], r[3]), reverse=True)
    conn.close()

    lines = ["🔼 ТОП по уровню:", ""]
    top_rows = rows[:10]
    scores = await asyncio.gather(*[get_user_score_cached(r[0]) for r in top_rows])
    for i, ((uid, uname, lvl, _), score) in enumerate(zip(top_rows, scores), 1):
        name = f"@{uname}" if uname else f"ID:{uid}"
        lines.append(f"{i}. {name}")
        lines.append(f"🔼 {lvl} ур.  🔥 {shorten_number(int(score))} очков")
        lines.append("")

    user_id = update.effective_user.id
    total = len(rows)
    rank = next((idx + 1 for idx, (uid, *_ ) in enumerate(rows) if uid == user_id), total)
    xp_val = int(next((xp for uid, _, _, xp in rows if uid == user_id), 0))
    score = int(await get_user_score_cached(user_id))
    _, user_lvl = db.get_xp_level(user_id)
    lines.append(f"👀 Ты — #{rank} из {total}")
    lines.append(f"🔼 {user_lvl} ур.  🔥 {shorten_number(score)} очков")
    if rank > 1:
        diff = int(rows[rank-2][3] - xp_val)
        lines.append(f"🚀 До следующего места: {shorten_number(diff)} XP")

    text = "\n".join(lines).rstrip()
    await _send_rank_text(update, text)


@require_subscribe
async def rank_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    if data == "rank_top":
        await top(update, context)
    elif data == "rank_xp":
        await topxp(update, context)
    elif data == "rank_ref":
        await topref(update, context)
    elif data == "rank_week":
        await topweek(update, context)


@require_subscribe
async def rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show rating menu with inline buttons."""
    buttons = [
        [InlineKeyboardButton("🏆 ТОП по очкам", callback_data="rank_top")],
        [InlineKeyboardButton("🔼 ТОП по уровню", callback_data="rank_xp")],
        [InlineKeyboardButton("🫂 ТОП по приглашениям", callback_data="rank_ref")],
        [InlineKeyboardButton("⚡️ Прирост за неделю", callback_data="rank_week")],
    ]
    await update.message.reply_text(
        "📊 Выбери рейтинг:", reply_markup=InlineKeyboardMarkup(buttons)
    )


def _collection_root_markup():
    buttons = [
        [InlineKeyboardButton("💎 Редкость", callback_data="coll_filter_rarity")],
        [InlineKeyboardButton("🏒 Клубы", callback_data="coll_filter_club")],
        [InlineKeyboardButton("♻️ Повторки", callback_data="coll_filter_dupes")],
        [InlineKeyboardButton("🆕 Новые", callback_data="coll_filter_new")],
        [InlineKeyboardButton("🧊 В команде", callback_data="coll_filter_team")],
        [InlineKeyboardButton("📦 Все карточки", callback_data="coll_all")],
    ]
    return InlineKeyboardMarkup(buttons)


def _reset_collection_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove current collection view state."""
    context.user_data.pop("coll", None)


async def send_club_list_page(chat_id, context, user_id, page=0, *, edit=False, message_id=None):
    all_keys = get_all_club_keys()
    totals = get_club_total_counts()
    user_cnt = get_user_club_counts(user_id)
    per_page = 8
    total_pages = (len(all_keys) + per_page - 1) // per_page
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    end = start + per_page
    page_keys = all_keys[start:end]
    buttons = []
    for key in page_keys:
        have = user_cnt.get(key, 0)
        total = totals.get(key, 0)
        label = f"{key} — {have} из {total}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"coll_club_{key}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Назад", callback_data=f"coll_clubpage_{page-1}"))
    nav.append(InlineKeyboardButton("🔙 В коллекцию", callback_data="coll_back"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Вперёд ▶️", callback_data=f"coll_clubpage_{page+1}"))
    markup = InlineKeyboardMarkup(buttons + ([nav] if nav else []))

    text = "Выбери клуб:"
    if edit and message_id:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup)
    else:
        await context.bot.send_message(chat_id, text, reply_markup=markup)


async def collection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _reset_collection_state(context)
    context.user_data["coll_nav"] = ["collection"]
    await update.message.reply_text(
        "📂 Управление коллекцией:", reply_markup=_collection_root_markup()
    )


async def collection_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    uid = query.from_user.id
    await query.answer()

    nav = context.user_data.setdefault("coll_nav", ["collection"])

    async def show_state(state):
        async def send_or_edit(text: str, markup: InlineKeyboardMarkup):
            if query.message and query.message.photo:
                await query.message.delete()
                await context.bot.send_message(query.message.chat_id, text, reply_markup=markup)
            else:
                await query.edit_message_text(text, reply_markup=markup)

        if state == "collection":
            await send_or_edit("📂 Управление коллекцией:", _collection_root_markup())
            return
        if state == "rarity_select":
            buttons = [
                [InlineKeyboardButton(f"{RARITY_EMOJI.get(r,'')} {RARITY_RU_SHORT[r]}", callback_data=f"coll_rarity_{r}")]
                for r in ["legendary", "mythic", "epic", "rare", "common"]
            ]
            buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="coll_back")])
            await send_or_edit("Выбери редкость:", InlineKeyboardMarkup(buttons))
            return
        if state.startswith("rarity_"):
            rarity = state.split("_", 1)[1]
            cards = build_filtered_cards(uid, rarity=rarity)
            context.user_data["coll"] = {"rarity": rarity, "mode": "carousel", "index": 0, "cards": cards}
            await send_card_page(query.message.chat_id, context, cards, index=0, user_id=uid, edit=True, message_id=query.message.message_id)
            return
        if state.startswith("clubpage_"):
            page = int(state.split("_")[1])
            if query.message and query.message.photo:
                await query.message.delete()
                await send_club_list_page(query.message.chat_id, context, uid, page=page)
            else:
                await send_club_list_page(query.message.chat_id, context, uid, page=page, edit=True, message_id=query.message.message_id)
            return
        if state.startswith("club_"):
            club = state[5:]
            cards = build_filtered_cards(uid, club=club)
            context.user_data["coll"] = {"club": club, "mode": "carousel", "index": 0, "cards": cards}
            await send_card_page(query.message.chat_id, context, cards, index=0, user_id=uid, edit=True, message_id=query.message.message_id)
            return
        if state == "duplicates":
            cards = build_filtered_cards(uid, duplicates=True)
            context.user_data["coll"] = {"duplicates": True, "mode": "carousel", "index": 0, "cards": cards}
            await send_card_page(query.message.chat_id, context, cards, index=0, user_id=uid, edit=True, message_id=query.message.message_id)
            return
        if state == "new":
            cards = build_filtered_cards(uid, new_only=True)
            context.user_data["coll"] = {"new_only": True, "mode": "carousel", "index": 0, "cards": cards}
            await send_card_page(query.message.chat_id, context, cards, index=0, user_id=uid, edit=True, message_id=query.message.message_id)
            return
        if state == "team":
            cards, _ = get_team_cards(uid)
            context.user_data["coll"] = {"team": True, "mode": "carousel", "index": 0, "cards": cards}
            await send_card_page(query.message.chat_id, context, cards, index=0, user_id=uid, edit=True, message_id=query.message.message_id)
            return
        if state.startswith("all_page_"):
            page = int(state.split("_")[2])
            context.user_data["coll"] = {"page": page, "mode": "list"}
            await send_collection_page(query.message.chat_id, uid, context, page=page, edit_message=True, message_id=query.message.message_id)
            return

    if data == "coll_back":
        if len(nav) > 1:
            nav.pop()
        state = nav[-1]
        context.user_data["coll_nav"] = nav
        _reset_collection_state(context)
        await show_state(state)
        return

    if data == "coll_filter_rarity":
        nav.append("rarity_select")
        context.user_data["coll_nav"] = nav
        await show_state("rarity_select")
        return

    if data.startswith("coll_rarity_"):
        rarity = data.split("_", 2)[2]
        nav.append(f"rarity_{rarity}")
        context.user_data["coll_nav"] = nav
        await show_state(f"rarity_{rarity}")
        return

    if data == "coll_filter_club":
        nav.append("clubpage_0")
        context.user_data["coll_nav"] = nav
        await send_club_list_page(query.message.chat_id, context, uid, page=0, edit=True, message_id=query.message.message_id)
        return

    if data.startswith("coll_clubpage_"):
        page = int(data.split("_")[2])
        nav.append(f"clubpage_{page}")
        context.user_data["coll_nav"] = nav
        await send_club_list_page(query.message.chat_id, context, uid, page=page, edit=True, message_id=query.message.message_id)
        return

    if data.startswith("coll_club_"):
        club = data.replace("coll_club_", "", 1)
        nav.append(f"club_{club}")
        context.user_data["coll_nav"] = nav
        await show_state(f"club_{club}")
        return

    if data == "coll_filter_dupes":
        nav.append("duplicates")
        context.user_data["coll_nav"] = nav
        await show_state("duplicates")
        return

    if data == "coll_filter_new":
        nav.append("new")
        context.user_data["coll_nav"] = nav
        await show_state("new")
        return

    if data == "coll_filter_team":
        nav.append("team")
        context.user_data["coll_nav"] = nav
        await show_state("team")
        return

    if data == "coll_all":
        nav.append("all_page_0")
        context.user_data["coll_nav"] = nav
        context.user_data["coll"] = {"page": 0, "mode": "list"}
        await send_collection_page(query.message.chat_id, uid, context, page=0, edit_message=True, message_id=query.message.message_id)
        return

    if data in {"coll_next", "coll_prev"}:
        state = context.user_data.get("coll", {})
        if state.get("mode") == "carousel":
            idx = state.get("index", 0)
            if data == "coll_next":
                idx += 1
            else:
                idx = max(0, idx - 1)
            cards = state.get("cards", [])
            idx = max(0, min(idx, len(cards) - 1))
            state["index"] = idx
            context.user_data["coll"] = state
            await send_card_page(
                query.message.chat_id,
                context,
                cards,
                index=idx,
                user_id=uid,
                edit=True,
                message_id=query.message.message_id,
            )
        else:
            page = state.get("page", 0)
            if data == "coll_next":
                page += 1
            else:
                page = max(0, page - 1)
            state["page"] = page
            context.user_data["coll"] = state
            if context.user_data.get("coll_nav"):
                context.user_data["coll_nav"][-1] = f"all_page_{page}"
            await send_collection_page(
                query.message.chat_id,
                uid,
                context,
                page=page,
                rarity=state.get("rarity"),
                club=state.get("club"),
                new_only=state.get("new_only", False),
                duplicates=state.get("duplicates", False),
                edit_message=True,
                message_id=query.message.message_id,
            )
        return



async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Твой Telegram user_id: {update.effective_user.id}")

@admin_only
async def whoisadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает информацию о пользователе и права администратора."""
    requester_id = update.effective_user.id

    uid = None
    if context.args:
        arg = context.args[0]
        if arg.isdigit():
            uid = int(arg)
        else:
            username = arg.lstrip("@")
            conn = get_db()
            c = conn.cursor()
            c.execute(
                "SELECT id FROM users WHERE lower(username)=lower(?)", (username,)
            )
            row = c.fetchone()
            conn.close()
            if row:
                uid = row[0]
            else:
                await update.message.reply_text("Пользователь не найден.")
                return
    elif update.message.reply_to_message:
        uid = update.message.reply_to_message.from_user.id

    if uid is None:
        conn = get_db()
        c = conn.cursor()
        lines = []
        for user_id in sorted(admin_usage_log):
            c.execute("SELECT username FROM users WHERE id=?", (user_id,))
            row = c.fetchone()
            username = row[0] if row else None
            if username:
                username = escape_markdown(username, version=1)
            cmds = sorted(
                escape_markdown(cmd, version=1) for cmd in admin_usage_log.get(user_id, [])
            )
            name = f"@{username}" if username else "—"
            lines.append(f"👤 ID: {user_id} | {name}")
            used = ", ".join(cmds) if cmds else "—"
            lines.append(f"• Использовал: {used}")
            lines.append(
                f"• Был админом ранее: {'✅' if user_id in was_admin_before else '❌'}"
            )
            lines.append(
                f"• Сейчас в ADMINS: {'✅' if user_id in ADMINS else '❌'}"
            )
            lines.append("")
        conn.close()
        total = len(admin_usage_log)
        lines.append(
            f"Всего пользователей, использовавших админ-функции: {total}"
        )
        await update.message.reply_text("\n".join(lines).rstrip())
        return

    # detailed info for selected uid
    record_admin_usage(requester_id, "/whoisadmin")

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE id=?", (uid,))
    row = c.fetchone()
    conn.close()
    username = row[0] if row else None
    if username:
        username = escape_markdown(username, version=1)

    xp, lvl = db.get_xp_level(uid)
    cap = xp + xp_to_next(xp)
    rank, total = await get_user_rank_cached(uid)

    in_admins = uid in ADMINS
    no_cd = uid in admin_no_cooldown
    has_panel = is_admin(uid)
    passes_sub = True if has_panel else await is_user_subscribed(context.bot, uid)
    used_cmds = sorted(escape_markdown(cmd, version=1) for cmd in admin_usage_log.get(uid, []))

    lines = [
        f"👤 ID: {uid}",
        f"🔗 Username: @{username}" if username else "🔗 Username: —",
        "",
        "🔍 Права:",
        f"• В ADMINS: {'✅' if in_admins else '❌'}",
        f"• В admin_no_cooldown: {'✅' if no_cd else '❌'}",
        f"• Админ-панель доступна: {'✅' if has_panel else '❌'}",
        f"• Проходит подписку без проверки: {'✅' if passes_sub else '❌'}",
    ]

    if uid in was_admin_before:
        lines.append("\n🕰 Был админом ранее")
    if used_cmds:
        lines.extend(["", f"🛠 Использованные команды: {', '.join(used_cmds)}"])

    lines.extend([
        "",
        f"📈 Уровень: {lvl}  | XP: {xp} / {cap}",
        f"🏆 Рейтинг: #{rank} из {total}",
    ])

    markup = None
    if is_admin(requester_id) and in_admins and requester_id != uid:
        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Удалить из ADMINS", callback_data=f"remove_admin_{uid}")]]
        )
        lines.append("\n⚠️ Рекомендация: если это неадмин — нажми \"Удалить\"")

    text = "\n".join(lines)
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)

@admin_only
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show available admin commands."""
    user_id = update.effective_user.id
    record_admin_usage(user_id, "/admin_panel")
    text = (
        "⚙️ *Админ-панель*\n\n"
        "/nocooldown — снять кулдаун\n"
        "/editcard — редактировать карточки\n"
        "/giveallcards — выдать все недостающие\n"
        "/resetweek — обнулить недельный прирост\n"
        "/deletecard <имя> — удалить карту по имени\n"
        "/ban <id> — заблокировать пользователя\n"
        "/unban <id> — разблокировать пользователя\n"
        "/logadmin — последние действия админов\n"
        "/admintop — топ админов\n"
        "/stats — статистика\n"
        "/broadcast <текст> — рассылка\n"
        "/whoonline — кто онлайн\n"
        "/whoisadmin <ID|@user> — информация об админах"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

@admin_only
async def nocooldown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    record_admin_usage(user_id, "/nocooldown")
    if user_id in admin_no_cooldown:
        admin_no_cooldown.remove(user_id)
        await update.message.reply_text("❄️ Ограничение по времени снова включено для вас.")
    else:
        admin_no_cooldown.add(user_id)
        await update.message.reply_text("🔥 Ограничение по времени для вас отключено!")

@admin_only
async def deletecard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    record_admin_usage(user_id, "/deletecard")
    if not context.args:
        await update.message.reply_text("⚠️ Укажите имя игрока после команды (например: /deletecard Коннор МакДэвид)")
        return
    name = " ".join(context.args)
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id FROM cards WHERE name = ?', (name,))
    row = c.fetchone()
    if not row:
        await update.message.reply_text(f"Не найдено карточки с именем: {name}")
    else:
        c.execute('DELETE FROM cards WHERE id = ?', (row[0],))
        conn.commit()
        await update.message.reply_text(f"Карточка игрока '{name}' удалена.")
        refresh_card_cache(row[0])
    conn.close()

@admin_only
async def giveallcards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    record_admin_usage(user_id, "/giveallcards")

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM cards")
    all_ids = {row[0] for row in c.fetchall()}
    c.execute("SELECT card_id FROM inventory WHERE user_id=?", (user_id,))
    have_ids = {row[0] for row in c.fetchall()}
    missing = all_ids - have_ids

    now = int(time.time())
    for cid in missing:
        c.execute(
            "INSERT INTO inventory (user_id, card_id, time_got) VALUES (?, ?, ?)",
            (user_id, cid, now),
        )
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ Выдано {len(missing)} новых карточек."
    )

EDIT_CARDS_PER_PAGE = 20

@admin_only
async def editcard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    record_admin_usage(user_id, "/editcard")
    admin_edit_state[user_id] = {"step": "list"}
    await send_editcard_list(update.message.chat_id, context, 0, user_id)

async def send_editcard_list(chat_id, context, page, user_id, edit_message_id=None):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name, rarity FROM cards ORDER BY rarity, name")
    cards = c.fetchall()
    conn.close()
    total = len(cards)
    total_pages = (total + EDIT_CARDS_PER_PAGE - 1) // EDIT_CARDS_PER_PAGE
    start = page * EDIT_CARDS_PER_PAGE
    end = start + EDIT_CARDS_PER_PAGE
    page_cards = cards[start:end]
    buttons = []
    for cid, name, rarity in page_cards:
        text = f"{name} ({RARITY_RU.get(rarity, rarity)})"
        buttons.append([InlineKeyboardButton(text, callback_data=f"adminedit_{cid}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"admineditpage_{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"admineditpage_{page+1}"))
    markup = InlineKeyboardMarkup(buttons + ([nav] if nav else []))
    msg = f"Выберите карточку для редактирования (стр {page+1} из {total_pages}):"
    if edit_message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=edit_message_id,
                text=msg,
                reply_markup=markup
            )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                pass  # просто игнорируем
            else:
                raise
    else:
        await context.bot.send_message(chat_id, msg, reply_markup=markup)

async def editcard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    # Навигация по страницам
    if data.startswith("admineditpage_"):
        page = int(data.split("_")[1])
        await send_editcard_list(query.message.chat_id, context, page, user_id, query.message.message_id)
        await query.answer()
        return

    # Выбор карточки
    if data.startswith("adminedit_"):
        card_id = int(data.split("_")[1])
        admin_edit_state[user_id] = {"step": "choose_action", "card_id": card_id}
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Редактировать очки/статы", callback_data="admineditstat")],
            [InlineKeyboardButton("⭐️ Редактировать редкость", callback_data="admineditrarity")],
            [InlineKeyboardButton("✍️ Переименовать", callback_data="admineditname")],
            [InlineKeyboardButton("Назад", callback_data="admineditpage_0")]
        ])
        # Получим имя карточки
        card = get_card_from_cache(card_id)
        name = card["name"] if card else "карточка"
        text = f"Выбрана: <b>{name}</b>\nЧто редактировать?"
        await query.edit_message_text(text, reply_markup=markup, parse_mode='HTML')
        await query.answer()
        return

    # Выбор действия (очки или редкость)
    if data == "admineditstat":
        admin_edit_state[user_id]["step"] = "edit_stats"
        await query.edit_message_text("Введите новое значение для поля <b>stats</b> (например: Очки 88 или Поб 33 КН 2.22):", parse_mode='HTML')
        await query.answer()
        return
    if data == "admineditrarity":
        admin_edit_state[user_id]["step"] = "edit_rarity"
        # Список доступных редкостей
        buttons = [
            [InlineKeyboardButton(RARITY_RU[r], callback_data=f"adminsetrarity_{r}")]
            for r in RARITY_ORDER.keys()
        ]
        markup = InlineKeyboardMarkup(buttons)
        await query.edit_message_text("Выберите новую редкость:", reply_markup=markup)
        await query.answer()
        return
    if data == "admineditname":
        admin_edit_state[user_id]["step"] = "edit_name"
        card_id = admin_edit_state[user_id].get("card_id")
        card = get_card_from_cache(card_id)
        name = card["name"] if card else "игрока"
        await query.edit_message_text(f"✍️ Введи новое имя для {name}:")
        await query.answer()
        return

    # Выбор редкости из списка
    if data.startswith("adminsetrarity_"):
        rarity = data.split("_")[1]
        card_id = admin_edit_state[user_id].get("card_id")
        if not card_id:
            await query.answer("Ошибка! Карточка не выбрана.")
            return
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE cards SET rarity = ? WHERE id = ?", (rarity, card_id))
        c.execute("SELECT name FROM cards WHERE id = ?", (card_id,))
        row = c.fetchone()
        conn.commit()
        name = row[0] if row else "карточка"
        conn.close()
        refresh_card_cache(card_id)
        invalidate_score_cache_for_card(card_id)
        await query.edit_message_text(f"✅ Редкость карточки <b>{name}</b> обновлена на: {RARITY_RU[rarity]}", parse_mode='HTML')
        admin_edit_state.pop(user_id, None)
        await query.answer()
        return

async def admin_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in admin_edit_state:
        return
    state = admin_edit_state[user_id]
    if state.get("step") == "edit_stats":
        card_id = state.get("card_id")
        card = get_card_from_cache(card_id)
        raw_input = update.message.text
        pos = card["pos"] if card else ""
        new_stats = normalize_stats_input(raw_input, pos)
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE cards SET stats = ? WHERE id = ?", (new_stats, card_id))
        c.execute("SELECT name FROM cards WHERE id = ?", (card_id,))
        row = c.fetchone()
        conn.commit()
        name = row[0] if row else "карточка"
        conn.close()
        update_card_points(card_id)
        refresh_card_cache(card_id)
        invalidate_score_cache_for_card(card_id)
        SCORE_CACHE.clear()
        await update.message.reply_text("✅ Очки обновлены!")
    elif state.get("step") == "edit_name":
        card_id = state.get("card_id")
        new_name = update.message.text.strip()
        db.update_player_name(card_id, new_name)
        refresh_card_cache(card_id)
        await update.message.reply_text(f"✅ Игрок теперь известен как {new_name}!")
    admin_edit_state.pop(user_id, None)

async def admin_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if not is_admin(user_id):
        await query.answer("Недостаточно прав", show_alert=True)
        return
    target_id = int(query.data.split("_")[-1])
    if target_id == user_id:
        await query.answer("Нельзя удалить себя", show_alert=True)
        return
    if target_id in ADMINS:
        ADMINS.remove(target_id)
        was_admin_before.add(target_id)
        text = query.message.text
        if "✅ Удалён" not in text:
            text += "\n\n✅ Удалён"
        await query.edit_message_text(text, parse_mode="Markdown")
        await query.answer("Удалён")
    else:
        await query.answer("🤔 Этот пользователь уже не админ.", show_alert=True)


@admin_only
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    record_admin_usage(user_id, "/ban")
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Укажите ID пользователя после команды.")
        return
    target = int(context.args[0])
    banned_users.add(target)
    await update.message.reply_text(f"Пользователь {target} заблокирован.")


@admin_only
async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    record_admin_usage(user_id, "/unban")
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Укажите ID пользователя после команды.")
        return
    target = int(context.args[0])
    banned_users.discard(target)
    await update.message.reply_text(f"Пользователь {target} разблокирован.")


@admin_only
async def logadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    record_admin_usage(user_id, "/logadmin")
    conn = get_db()
    c = conn.cursor()
    entries = admin_action_history[-20:][::-1]
    lines = []
    for ts, uid, cmd in entries:
        c.execute("SELECT username FROM users WHERE id=?", (uid,))
        row = c.fetchone()
        name = f"@{row[0]}" if row and row[0] else str(uid)
        dt = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        lines.append(f"{dt} | {name} → {cmd}")
    conn.close()
    await update.message.reply_text("\n".join(lines) if lines else "Лог пуст.")


@admin_only
async def admintop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    record_admin_usage(user_id, "/admintop")
    conn = get_db()
    c = conn.cursor()
    items = sorted(admin_usage_count.items(), key=lambda x: x[1], reverse=True)
    lines = []
    for i, (uid, cnt) in enumerate(items[:10], 1):
        c.execute("SELECT username FROM users WHERE id=?", (uid,))
        row = c.fetchone()
        name = f"@{row[0]}" if row and row[0] else str(uid)
        lines.append(f"{i}. {name} — {cnt}")
    conn.close()
    await update.message.reply_text("\n".join(lines) if lines else "Нет данных.")


@admin_only
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    record_admin_usage(user_id, "/stats")
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    start_day = int(datetime.datetime.combine(datetime.date.today(), datetime.time.min).timestamp())
    c.execute("SELECT COUNT(*) FROM inventory WHERE time_got >= ?", (start_day,))
    packs_today = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM inventory")
    total_cards = c.fetchone()[0]
    c.execute("SELECT SUM(xp) FROM users")
    total_xp = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM battles")
    total_battles = c.fetchone()[0]
    conn.close()
    text = (
        f"Пользователей: {total_users}\n"
        f"Паков сегодня: {packs_today}\n"
        f"Карточек выдано: {total_cards}\n"
        f"Начислено XP: {total_xp}\n"
        f"Боёв проведено: {total_battles}"
    )
    await update.message.reply_text(text)


@admin_only
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    record_admin_usage(user_id, "/broadcast")
    if not context.args:
        await update.message.reply_text("Укажите текст рассылки после команды.")
        return
    text = " ".join(context.args)
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM users")
    ids = [row[0] for row in c.fetchall()]
    conn.close()
    sent = 0
    for uid in ids:
        try:
            await context.bot.send_message(uid, text)
            sent += 1
        except Exception:
            pass
    await update.message.reply_text(f"Отправлено {sent} пользователям.")


@admin_only
async def whoonline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    record_admin_usage(user_id, "/whoonline")
    now = time.time()
    active = [uid for uid, ts in online_users.items() if now - ts <= 600]
    conn = get_db()
    c = conn.cursor()
    names = []
    for uid in active:
        c.execute("SELECT username FROM users WHERE id=?", (uid,))
        row = c.fetchone()
        names.append(f"@{row[0]}" if row and row[0] else str(uid))
    conn.close()
    if names:
        await update.message.reply_text("Сейчас онлайн:\n" + "\n".join(names))
    else:
        await update.message.reply_text("Никого нет онлайн.")

TEMP_DICTS = [
    pending_trades,
    trade_confirmations,
    admin_edit_state,
]

async def track_user_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Record last activity time for a user."""
    if update.effective_user:
        online_users[update.effective_user.id] = time.time()

async def cleanup_expired(context: ContextTypes.DEFAULT_TYPE):
    now = time.time()
    TTL = 24 * 3600
    for d in TEMP_DICTS:
        for k in list(d.keys()):
            created = d[k].get("created", now)
            if now - created > TTL:
                d.pop(k, None)
    handlers.cleanup_pvp_queue()
    # cleanup online users older than 10 minutes
    for uid, ts in list(online_users.items()):
        if now - ts > 600:
            online_users.pop(uid, None)

async def post_init(application: Application):
    bot_commands = [
        BotCommand("menu", "Главное меню"),
        BotCommand("card", "Получить карточку"),
        BotCommand("collection", "Моя коллекция"),
        BotCommand("me", "Мой профиль"),
        BotCommand("fight", "Бой с ботом"),
        BotCommand("duel", "Дуэль с игроком"),
        BotCommand("duel_list", "Кто ждёт дуэль"),
        BotCommand("invite", "Пригласить друга"),
    ]
    await application.bot.set_my_commands(bot_commands)


def safe_polling(app):
    while True:
        try:
            app.run_polling()
        except NetworkError as e:
            logging.warning(f"Network error: {e}. Retrying in 10 sec...")
            time.sleep(10)
        except Exception as e:
            logging.exception("Unexpected error in polling:", exc_info=e)
            time.sleep(10)

def main():
    setup_db()
    db.setup_battle_db()
    db.setup_team_db()
    application = (
        Application.builder()
        .token(TOKEN)
        .persistence(DictPersistence())
        .post_init(post_init)
        .build()
    )
    application.job_queue.run_repeating(cleanup_expired, interval=3600)

    # track user activity
    application.add_handler(
        MessageHandler(filters.ALL, track_user_activity, block=False), group=20
    )
    application.add_handler(
        CallbackQueryHandler(track_user_activity, pattern=".*", block=False),
        group=20,
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu))
    application.add_handler(CommandHandler("card", card))
    application.add_handler(CommandHandler("myid", myid))
    application.add_handler(CommandHandler("whoisadmin", whoisadmin))
    application.add_handler(CommandHandler("ban", ban))
    application.add_handler(CommandHandler("unban", unban))
    application.add_handler(CommandHandler("logadmin", logadmin))
    application.add_handler(CommandHandler("admintop", admintop))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("whoonline", whoonline))
    application.add_handler(CommandHandler("nocooldown", nocooldown))
    application.add_handler(CommandHandler("deletecard", deletecard))
    application.add_handler(CommandHandler("giveallcards", giveallcards))
    application.add_handler(CommandHandler("me", me))
    application.add_handler(CommandHandler("xp", xp))
    application.add_handler(CommandHandler("topxp", topxp))
    application.add_handler(CommandHandler("resetweek", resetweek))
    application.add_handler(CommandHandler("trade", trade))
    application.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu_"))
    application.add_handler(CallbackQueryHandler(trade_callback, pattern="^trade_"))
    application.add_handler(CommandHandler("collection", collection))
    application.add_handler(CallbackQueryHandler(collection_callback, pattern="^coll_"))
    application.add_handler(CallbackQueryHandler(trade_page_callback, pattern="^trade_page_(prev|next)$"))
    application.add_handler(CommandHandler("editcard", editcard))
    application.add_handler(CallbackQueryHandler(editcard_callback, pattern="^(adminedit|admineditpage|admineditstat|admineditrarity|admineditname|adminsetrarity)_?"))
    application.add_handler(CommandHandler("rename_player", handlers.rename_player))
    application.add_handler(CallbackQueryHandler(handlers.rename_select_callback, pattern="^rename_select:\d+$"))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handlers.rename_player_text), group=5)
    application.add_handler(CommandHandler("myteam", handlers.show_my_team))
    application.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), admin_text_handler),
        group=5,
    )
    application.add_handler(CallbackQueryHandler(check_subscribe_callback, pattern="^check_subscribe$"))
    application.add_handler(CommandHandler("invite", invite))
    application.add_handler(CommandHandler("rank", rank))
    application.add_handler(CallbackQueryHandler(rank_callback, pattern="^rank_"))
    application.add_handler(CommandHandler("team", handlers.create_team))
    application.add_handler(CallbackQueryHandler(handlers.team_callback, pattern="^team_"))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handlers.team_text_handler))
    application.add_handler(CallbackQueryHandler(admin_remove_callback, pattern="^remove_admin_\d+$"))
    application.add_handler(CallbackQueryHandler(open_team, pattern="^open_team$"))
    application.add_handler(CommandHandler("fight", handlers.start_fight))
    application.add_handler(CommandHandler("duel", handlers.start_duel))
    application.add_handler(CommandHandler("duel_list", handlers.duel_list))
    application.add_handler(CommandHandler("history", handlers.show_battle_history))
    application.add_handler(CallbackQueryHandler(handlers.tactic_callback, pattern="^tactic_"))
    application.add_handler(CallbackQueryHandler(handlers.battle_callback, pattern="^dir_"))
    application.add_handler(CallbackQueryHandler(handlers.battle_callback, pattern="^battle_"))
    application.add_handler(CallbackQueryHandler(handlers.duel_callback, pattern="^(challenge_\\d+|duel_cancel)$"))






    safe_polling(application)

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    main()
