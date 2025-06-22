import os
import time
import random
import sqlite3
import re
import asyncio
import telegram

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
)
from telegram.error import BadRequest
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    BotCommand,
    Update,
)
from collections import Counter
from functools import wraps
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


TOKEN = "7649956181:AAErINkWzZJ7BofoorAHxc2fLXMPoaCjkQM"
ADMINS = {445479731, 6463889816}
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

RARITY_ORDER = {
    "legendary": 0,
    "mythic": 1,
    "epic": 2,
    "rare": 3,
    "common": 4
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

# --- Кэш для карточек ---
CARD_FIELDS = [
    "id", "name", "img", "pos", "country", "born", "height",
    "weight", "rarity", "stats", "team_en", "team_ru"
]
CARD_CACHE = {}

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
user_carousel = {}

# --- Новое для листалки mycards
user_cards_pagination = {}
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
    conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'botdb.sqlite'))
    return conn

def setup_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT, last_card_time INTEGER)')
    try:
        c.execute("ALTER TABLE users ADD COLUMN last_week_score INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN referrals_count INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN invited_by INTEGER DEFAULT NULL")
    except sqlite3.OperationalError:
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
        'AND img NOT LIKE "%default-skater.png%" '
        'AND img NOT LIKE "%default-goalie.png%" '
        'AND img != "" AND img IS NOT NULL '
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

def is_admin(user_id):
    return user_id in ADMINS

async def send_ranking_push(user_id, context, chat_id):
    # теперь пушим всем (можно и админам)
    rank, total = await get_user_rank(user_id)
    if rank > total:
        return
    if rank <= 5:
        msg = f"Ты уже в ТОП-5 — круто! Продолжай собирать и держись в лидерах! 🏒"
    else:
        top5 = await get_top_users(limit=5)
        user_score = await calculate_user_score(user_id)
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

# ------- ОЧКИ и РЕЙТИНГИ -----------
def parse_points(stats, pos):
    if pos == "G":
        win = 0
        gaa = 3.0
        m_win = re.search(r'Поб\s+(\d+)', stats or "")
        m_gaa = re.search(r'КН\s*([\d.]+)', stats or "")
        if m_win:
            win = int(m_win.group(1))
        if m_gaa:
            gaa = float(m_gaa.group(1))
        return win * 2 + (30 - gaa * 10)
    else:
        m = re.search(r'Очки\s+(\d+)', stats or "")
        return int(m.group(1)) if m else 0

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

def _get_user_rank_sync(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM users")
    # Исключаем админов из рейтинга
    user_ids = [row[0] for row in c.fetchall() if row[0] not in ADMINS]
    scores = []
    for uid in user_ids:
        score = _calculate_user_score_sync(uid)
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
    user_ids = [row[0] for row in c.fetchall() if row[0] not in ADMINS]
    conn.close()
    scores = await asyncio.gather(*[calculate_user_score(uid) for uid in user_ids])
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

def get_weekly_progress(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT last_week_score FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    current = _calculate_user_score_sync(user_id)
    last = row[0] if row else 0
    return current - last

def _get_top_users_sync(limit=10):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, username FROM users")
    # Исключаем админов из топа
    users = [(uid, uname) for (uid, uname) in c.fetchall() if uid not in ADMINS]
    user_scores = []
    for uid, uname in users:
        score = _calculate_user_score_sync(uid)
        user_scores.append((uid, uname, score))
    user_scores.sort(key=lambda x: x[2], reverse=True)
    conn.close()
    return user_scores[:limit]

async def get_top_users(*args, **kwargs):
    return await asyncio.to_thread(_get_top_users_sync, *args, **kwargs)

# ------- КОМАНДЫ РЕЙТИНГА ----------
@require_subscribe
async def me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_admin(user_id):
        await update.message.reply_text("У админов нет профиля в рейтинге.")
        return
    rank, total = await get_user_rank(user_id)
    progress = get_weekly_progress(user_id)
    score = await calculate_user_score(user_id)
    medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else ""
    msg = (
        f"👤 Твой профиль:\n"
        f"• Очки: {int(score)}\n"
        f"• Место в рейтинге: #{rank} из {total} {medal}\n"
        f"• Прирост за неделю: {('+' if progress >= 0 else '')}{int(progress)} очк{'а' if abs(progress)%10 in [2,3,4] else ''}{' — молодец!' if progress > 0 else ''}"
    )
    # === ДОБАВЛЯЕШЬ ВОТ ЭТИ 3 СТРОКИ ===
    referrals = get_referral_count(user_id)
    achv = get_referral_achievements(referrals)
    msg += f"\n\n👥 Приглашено: {referrals}\n{achv}"
    # ====================================
    await update.message.reply_text(msg)

@require_subscribe
async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top10 = await get_top_users(limit=10)
    text = (
        "🏆 ТОП-10 коллекционеров NHL:\n"
        "🔹 Полевой: 'Очки' на карточке\n"
        "🔹 Вратарь: Победы ×2 + (30 – КН×10)\n"
        "🔹 Чем реже карта, тем больше очков!\n\n"
    )
    for i, (uid, uname, score) in enumerate(top10, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else ""
        username = (f"@{uname}" if uname else f"ID:{uid}")
        text += f"{i}. {username} — {int(score)} {medal}\n"
    await update.message.reply_text(text)

@require_subscribe
async def top50(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top50 = await get_top_users(limit=50)
    text = "🏆 ТОП-50 коллекционеров NHL:\n\n"
    for i, (uid, uname, score) in enumerate(top50, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else ""
        username = (f"@{uname}" if uname else f"ID:{uid}")
        text += f"{i}. {username} — {int(score)} {medal}\n"
    await update.message.reply_text(text)

async def resetweek(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔️ Нет прав для этой команды.")
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM users")
    users = c.fetchall()
    for (uid,) in users:
        score = await calculate_user_score(uid)
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
    c.execute("INSERT OR IGNORE INTO users (id, username, last_card_time, invited_by, referrals_count) VALUES (?, ?, 0, NULL, 0)", (user_id, username))

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
    text = (
        "Добро пожаловать в коллекционный бот NHL!\n"
        "/card — получить карточку\n"
        "/mycards — твоя коллекция (листай кнопками)\n"
        "/mycards2 — коллекция с листанием по одной\n"
        "/me — твой рейтинг и прогресс\n"
        "/top — топ-10 игроков\n"
        "/top50 — топ-50 игроков\n"
        "/myid — узнать свой user_id\n"
        "/trade <user_id> — обмен картами по Telegram ID\n"
        "/invite — пригласи друга и получи ачивки!\n"
        "/topref — топ по приглашениям\n"
        "/clubs — карточки по клубам\n"
    )
    if is_admin(user_id):
        text += (
            "\n⚙️ Админ-команды:\n"
            "/nocooldown — снять/вернуть лимит времени\n"
            "/deletecard <имя игрока> — удалить карточку по имени\n"
            "/resetweek — обновить недельные приросты\n"
            "/editcard — редактировать картоки (очки и редкость)"
            "\n/giveallcards — выдать все недостающие карточки"
        )
    await update.message.reply_text(text)

@require_subscribe
async def card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
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

    pos_ru = pos_to_rus(card_obj.get('pos') or '')
    flag = flag_from_iso3(card_obj.get('country'))
    iso = card_obj.get('country', '').upper()
    club = (card_obj.get('team_ru') or card_obj.get('team_en') or "—").strip()

    caption = "\n".join(filter(None, [
        f"*{card_obj.get('name','?')}*",
        f"*Клуб:* {club}",
        f"_Позиция:_ {pos_ru}",
        f"*Страна:* {flag} `{iso}`",
        f"*Редкость:* {RARITY_RU.get(card_obj.get('rarity','common'), card_obj.get('rarity','common'))}",
        "────────────",
        wrap_line(card_obj.get('stats',''))
    ]))

    try:
        await context.bot.send_photo(update.message.chat_id, card_obj.get('img', ''), caption=caption, parse_mode='Markdown')
    except BadRequest:
        await update.message.reply_text(
            f"⚠️ Картинка карточки недоступна, но вот информация:\n{caption}",
            parse_mode='Markdown'
        )

    await send_ranking_push(user_id, context, update.message.chat_id)

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
    c.execute("DELETE FROM inventory WHERE user_id=? AND card_id=? LIMIT 1", (user_id, card_id))
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
    for cid, cnt in count_dict.items():
        card = get_card_from_cache(cid)
        if not card:
            continue
        card_copy = card.copy()
        card_copy["count"] = cnt
        cards.append(card_copy)

    return cards, sum(count_dict.values())

def get_all_club_keys():
    """Return sorted list of all club keys from team_en or team_ru."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """
        SELECT DISTINCT COALESCE(team_en, team_ru) AS club
          FROM cards
         WHERE club IS NOT NULL AND club != ''
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
         WHERE club IS NOT NULL AND club != ''
      GROUP BY club
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
           AND club IS NOT NULL AND club != ''
      GROUP BY club
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

async def send_cards_page(chat_id, user_id, context, page=0, edit_message=False, message_id=None):
    # Получаем все карточки пользователя
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT card_id FROM inventory WHERE user_id=?", (user_id,))
    card_ids = [r[0] for r in c.fetchall()]
    conn.close()

    count_dict = Counter(card_ids)

    if not card_ids:
        await context.bot.send_message(chat_id, "У тебя нет карточек.")
        return

    # Получаем инфу о каждой карточке для сортировки
    card_info = []
    for card_id, count in count_dict.items():
        card = get_card_from_cache(card_id)
        if not card:
            continue
        name = card["name"]
        rarity = card["rarity"]
        rarity_index = RARITY_ORDER.get(rarity, 99)
        card_info.append((rarity_index, name, card_id, count, rarity))

    # Сортируем: сначала по редкости, потом по имени
    card_info.sort(key=lambda x: (x[0], x[1]))

    # Постранично по 50
    start = page * CARDS_PER_PAGE
    end = start + CARDS_PER_PAGE
    page_cards = card_info[start:end]

    if not page_cards:
        await context.bot.send_message(chat_id, "На этой странице нет карточек.")
        return

    # Готовим текст
    lines = []
    for _, name, card_id, count, rarity in page_cards:
        rar_ru = RARITY_RU.get(rarity, rarity)
        line = f"{name} ({rar_ru})"
        if count > 1:
            line += f" x{count}"
        lines.append(line)

    # Навигация
    total_cards = len(card_info)
    total_pages = (total_cards + CARDS_PER_PAGE - 1) // CARDS_PER_PAGE

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Назад", callback_data="mycards_prev"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Вперёд ▶️", callback_data="mycards_next"))

    markup = InlineKeyboardMarkup([nav_buttons]) if nav_buttons else None

    text = (
        f"📦 Твоя коллекция (по редкости, страница {page+1} из {total_pages}):\n\n"
        + "\n".join(lines)
        + f"\n\nВсего уникальных карточек: {total_cards}"
    )

    if edit_message and message_id:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=markup
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=markup
        )
async def send_card_page(chat_id, user_id, context, edit_message=False, message_id=None):
    # Получаем текущий индекс карточки в "карусели"
    data = user_carousel[user_id]
    idx = data["idx"]
    cards = data["cards"]
    all_count = data["all_count"]
    card = cards[idx]

    name = card['name']
    img = card['img']
    rarity = card['rarity']
    stats = card['stats']
    club = card['team_ru'] or card['team_en'] or "—"
    pos_ru = pos_to_rus(card['pos'] or '')
    flag = flag_from_iso3(card['country'])
    iso = (card['country'] or '').upper()
    count = card['count']  # <-- Количество

    caption = f"*{name}*"
    if count > 1:
        caption += f" x{count}"
    caption += "\n"
    caption += f"*Клуб:* {club}\n"
    caption += f"_Позиция:_ {pos_ru}\n"
    caption += f"*Страна:* {flag} `{iso}`\n"
    caption += f"*Редкость:* {RARITY_RU.get(rarity, rarity)}\n"
    caption += "────────────\n"
    caption += wrap_line(stats or "")
    caption += f"\n\n[{idx+1} из {len(cards)} | Всего карт: {all_count}]"

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️", callback_data="prev"), InlineKeyboardButton("➡️", callback_data="next")]
    ])

    try:
        if edit_message and message_id:
            await context.bot.edit_message_media(
                chat_id=chat_id,
                message_id=message_id,
                media=InputMediaPhoto(media=img, caption=caption, parse_mode="Markdown"),
                reply_markup=markup
            )
        else:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=img,
                caption=caption,
                parse_mode="Markdown",
                reply_markup=markup
            )
    except BadRequest:
        # Если не удалось отправить фото — fallback на текст
        if edit_message and message_id:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"⚠️ Картинка карточки недоступна, но вот информация:\n\n{caption}",
                reply_markup=markup,
                parse_mode="Markdown"
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ Картинка карточки недоступна, но вот информация:\n\n{caption}",
                reply_markup=markup,
                parse_mode="Markdown"
            )

def get_referral_count(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT referrals_count FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

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
    c.execute("SELECT username, referrals_count FROM users WHERE referrals_count > 0 ORDER BY referrals_count DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Пока никто не приглашал друзей.")
        return
    medals = ["🥇","🥈","🥉"]
    text = "🏅 Топ-10 по приглашениям:\n\n"
    for i, (username, count) in enumerate(rows, 1):
        medal = medals[i-1] if i <= 3 else ""
        name = f"@{username}" if username else f"ID:{i}"
        text += f"{i}. {name} — {count} приглашённых {medal}\n"
    await update.message.reply_text(text)


@require_subscribe
async def clubs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    all_keys = get_all_club_keys()
    totals = get_club_total_counts()
    user_cnt = get_user_club_counts(uid)

    buttons = []
    for key in all_keys:
        have = user_cnt.get(key, 0)
        total = totals.get(key, 0)
        label = f"{key} {have}/{total}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"club_sel_{key}")])

    await update.message.reply_text(
        "Выбери клуб:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def mycards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.message.chat_id
    user_cards_pagination[user_id] = 0
    await send_cards_page(chat_id, user_id, context, page=0)

async def mycards_pagination_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    message_id = query.message.message_id

    page = user_cards_pagination.get(user_id, 0)
    if query.data == "mycards_next":
        page += 1
    elif query.data == "mycards_prev":
        page -= 1
    page = max(0, page)
    user_cards_pagination[user_id] = page
    try:
        await query.answer()
    except BadRequest:
        return
    await send_cards_page(chat_id, user_id, context, page=page, edit_message=True, message_id=message_id)

@require_subscribe
async def mycards2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cards, all_count = get_full_cards_for_user(user_id)
    if not cards:
        await update.message.reply_text("У тебя ещё нет карточек — получи первую командой /card!")
        return
    user_carousel[user_id] = {"cards": cards, "idx": 0, "all_count": all_count}
    await send_card_page(update.message.chat_id, user_id, context)

async def carousel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    user_id = query.from_user.id
    try:
        await query.answer()
    except BadRequest:
        return
    if user_id not in user_carousel:
        return
    if query.data == "next":
        user_carousel[user_id]["idx"] = (
            user_carousel[user_id]["idx"] + 1
        ) % len(user_carousel[user_id]["cards"])
    elif query.data == "prev":
        user_carousel[user_id]["idx"] = (
            user_carousel[user_id]["idx"] - 1
        ) % len(user_carousel[user_id]["cards"])
    await send_card_page(
        chat_id=query.message.chat_id,
        user_id=user_id,
        context=context,
        edit_message=True,
        message_id=query.message.message_id
    )


async def club_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    club_key = query.data.replace("club_sel_", "", 1)
    try:
        await query.answer()
    except BadRequest:
        pass
    cards, total = get_user_club_cards(user_id, club_key)
    if not cards:
        await query.edit_message_text("У тебя нет карточек этого клуба.")
        return

    cards.sort(key=lambda c: (RARITY_ORDER.get(c["rarity"], 99), c["name"]))
    user_carousel[user_id] = {"cards": cards, "idx": 0, "all_count": total}
    await send_card_page(query.message.chat_id, user_id, context)

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Твой Telegram user_id: {update.effective_user.id}")

async def nocooldown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔️ Нет прав для этой команды.")
        return
    if user_id in admin_no_cooldown:
        admin_no_cooldown.remove(user_id)
        await update.message.reply_text("❄️ Ограничение по времени снова включено для вас.")
    else:
        admin_no_cooldown.add(user_id)
        await update.message.reply_text("🔥 Ограничение по времени для вас отключено!")

async def deletecard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔️ Нет прав для этой команды.")
        return
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

async def giveallcards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("⛔️ Нет прав для этой команды.")
        return

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

    admin_edit_state = {}  # user_id: {step, card_id}
EDIT_CARDS_PER_PAGE = 20

async def editcard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔️ Нет прав для этой команды.")
        return
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
        new_stats = update.message.text
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE cards SET stats = ? WHERE id = ?", (new_stats, card_id))
        c.execute("SELECT name FROM cards WHERE id = ?", (card_id,))
        row = c.fetchone()
        conn.commit()
        name = row[0] if row else "карточка"
        conn.close()
        refresh_card_cache(card_id)
        await update.message.reply_text(f"✅ Поле <b>stats</b> карточки <b>{name}</b> обновлено на: <code>{new_stats}</code>", parse_mode='HTML')
        admin_edit_state.pop(user_id, None)

TEMP_DICTS = [
    pending_trades,
    trade_confirmations,
    user_carousel,
    user_cards_pagination,
    admin_edit_state,
]

async def cleanup_expired(context: ContextTypes.DEFAULT_TYPE):
    now = time.time()
    TTL = 24 * 3600
    for d in TEMP_DICTS:
        for k in list(d.keys()):
            created = d[k].get("created", now)
            if now - created > TTL:
                d.pop(k, None)

async def post_init(application: Application):
    bot_commands = [
        BotCommand("start", "Приветствие и справка"),
        BotCommand("card", "Получить новую карточку"),
        BotCommand("mycards", "Коллекция (листай кнопками)"),
        BotCommand("mycards2", "Коллекция по одной карточке"),
        BotCommand("myid", "Узнать свой user_id"),
        BotCommand("me", "Твой рейтинг и прогресс"),
        BotCommand("trade", "Обмен картами по ID"),
        BotCommand("top", "ТОП-10 игроков"),
        BotCommand("top50", "ТОП-50 игроков"),
        BotCommand("invite", "Пригласи друга и получи ачивки!"),
        BotCommand("topref", "ТОП по приглашениям"),
        BotCommand("clubs", "Карточки по клубам"),
    ]
    await application.bot.set_my_commands(bot_commands)

def main():
    setup_db()
    application = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )
    application.job_queue.run_repeating(cleanup_expired, interval=3600)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("card", card))
    application.add_handler(CommandHandler("mycards", mycards))
    application.add_handler(CommandHandler("mycards2", mycards2))
    application.add_handler(CommandHandler("myid", myid))
    application.add_handler(CommandHandler("nocooldown", nocooldown))
    application.add_handler(CommandHandler("deletecard", deletecard))
    application.add_handler(CommandHandler("giveallcards", giveallcards))
    application.add_handler(CommandHandler("me", me))
    application.add_handler(CommandHandler("top", top))
    application.add_handler(CommandHandler("top50", top50))
    application.add_handler(CommandHandler("resetweek", resetweek))
    application.add_handler(CommandHandler("trade", trade))
    application.add_handler(CallbackQueryHandler(trade_callback, pattern="^trade_"))
    application.add_handler(CallbackQueryHandler(mycards_pagination_callback, pattern="^mycards_(next|prev)$"))
    application.add_handler(CallbackQueryHandler(carousel_callback, pattern="^(next|prev)$"))
    application.add_handler(CallbackQueryHandler(trade_page_callback, pattern="^trade_page_(prev|next)$"))
    application.add_handler(CommandHandler("editcard", editcard))
    application.add_handler(CallbackQueryHandler(editcard_callback, pattern="^(adminedit|admineditpage|admineditstat|admineditrarity|adminsetrarity)_?"))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), admin_text_handler))
    application.add_handler(CallbackQueryHandler(check_subscribe_callback, pattern="^check_subscribe$"))
    application.add_handler(CommandHandler("invite", invite))
    application.add_handler(CommandHandler("topref", topref))
    application.add_handler(CommandHandler("clubs", clubs))
    application.add_handler(CommandHandler("club", clubs))
    application.add_handler(CallbackQueryHandler(club_callback, pattern="^club_sel_"))






    application.run_polling()

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    main()
