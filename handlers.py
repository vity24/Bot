from collections import OrderedDict
import random
import asyncio
import re
import time
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telegram.error import Forbidden
from helpers.permissions import admin_only, is_admin
from battle import BattleSession, BattleController, POSITION_EMOJI
import db_pg as db
from helpers.leveling import level_from_xp, xp_to_next, calc_battle_xp
from helpers.commentary import format_period_summary, format_final_summary


async def _safe_send_message(bot, chat_id: int, text: str, **kwargs) -> None:
    """Send a Telegram message and ignore forbidden errors."""
    try:
        await bot.send_message(chat_id, text, **kwargs)
    except Forbidden:
        logging.warning("Cannot send message to %s: forbidden", chat_id)
    except Exception as e:  # pragma: no cover - log unexpected send errors
        logging.exception("Error sending message to %s: %s", chat_id, e)

level_up_msg = "🆙 *Новый уровень!*  Ты достиг Lv {lvl}.\n🎁 Твой приз: {reward}"


async def grant_level_reward(uid: int, lvl: int, context: ContextTypes.DEFAULT_TYPE):
    conn = db.get_db()
    cur = conn.cursor()
    cards = []
    count = random.randint(1, 3)
    for _ in range(count):
        card = await get_random_card()
        if not card:
            continue
        cur.execute(
            "INSERT INTO inventory (user_id, card_id, time_got) VALUES (?, ?, EXTRACT(EPOCH FROM NOW())::bigint)",
            (uid, card["id"]),
        )
        cards.append(card)
    conn.commit()
    conn.close()

    reward_lines = [f"{RARITY_EMOJI.get(c.get('rarity','common'), '')} {c['name']}" for c in cards]
    reward_text = "\n".join(reward_lines) if reward_lines else "карты не выданы"
    await context.bot.send_message(
        uid,
        level_up_msg.format(lvl=lvl, reward=reward_text),
        parse_mode="Markdown",
    )


async def apply_xp(uid: int, result: dict, opponent_is_bot: bool, context: ContextTypes.DEFAULT_TYPE):
    streak = db.update_win_streak(uid, result.get("winner") == "team1")
    xp_gain = calc_battle_xp(result, is_pve=opponent_is_bot, streak=streak, strength_gap=result.get("str_gap", 0.0))
    old_xp, old_lvl = db.get_xp_level(uid)
    new_xp = old_xp + xp_gain
    new_lvl = level_from_xp(new_xp)
    db.update_xp(uid, new_xp, new_lvl, xp_gain)
    leveled_up = new_lvl > old_lvl
    if leveled_up:
        await grant_level_reward(uid, new_lvl, context)
    if xp_gain:
        await context.bot.send_message(uid, f"➕ +{xp_gain} XP", parse_mode="Markdown")
    return xp_gain, new_lvl, leveled_up


def _parse_points(stats: str | None, pos: str | None) -> float:
    """Extract point value from stats text."""
    if (pos or "") == "G":
        win = 0
        gaa = 3.0
        m_win = re.search(r"Поб\s+(\d+)", stats or "")
        m_gaa = re.search(r"КН\s*([\d.]+)", stats or "")
        if m_win:
            win = int(m_win.group(1))
        if m_gaa:
            gaa = float(m_gaa.group(1))
        return win * 2 + (30 - gaa * 10)
    m = re.search(r"Очки\s+(\d+)", stats or "")
    return float(m.group(1)) if m else 0.0


def _get_random_card_sync():
    conn = db.get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, pos, country, born, weight, rarity, stats, team_en, team_ru FROM cards ORDER BY RANDOM() LIMIT 1"
    )
    row = cur.fetchone()
    conn.close()
    if row:
        fields = [
            "id",
            "name",
            "pos",
            "country",
            "born",
            "weight",
            "rarity",
            "stats",
            "team_en",
            "team_ru",
        ]
        card = dict(zip(fields, row))
        card["points"] = _parse_points(card["stats"], card["pos"])
        return card
    return None


async def get_random_card():
    return await asyncio.to_thread(_get_random_card_sync)


def _get_user_cards_sync(user_id):
    conn = db.get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT cards.id, cards.name, cards.pos, cards.country, cards.born, cards.weight,
               cards.rarity, cards.stats, cards.team_en, cards.team_ru
          FROM inventory
          JOIN cards ON inventory.card_id = cards.id
         WHERE inventory.user_id = ?
        """,
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()

    cards = []
    for row in rows:
        fields = [
            "id",
            "name",
            "pos",
            "country",
            "born",
            "weight",
            "rarity",
            "stats",
            "team_en",
            "team_ru",
        ]
        card = dict(zip(fields, row))
        card["points"] = _parse_points(card["stats"], card["pos"])
        cards.append(card)
    return cards


async def get_user_cards(user_id):
    return await asyncio.to_thread(_get_user_cards_sync, user_id)

# TTL for entries in PVP queue, seconds
PVP_TTL = 600
PVP_QUEUE = OrderedDict()

# Active PvP duels mapped by a tuple of user ids
ACTIVE_DUELS: dict[tuple[int, int], dict] = {}
# Map user id to current duel key
DUEL_USERS: dict[int, tuple[int, int]] = {}

TACTICS = {
    "tactic_aggressive": "aggressive",
    "tactic_defensive": "defensive",
    "tactic_balanced": "balanced",
}

# map direction callbacks to attack direction values
DIR_MAP = {
    "dir_left": "left",
    "dir_center": "center",
    "dir_right": "right",
}

# simple mapping of rarity to emoji for buttons
RARITY_EMOJI = {
    "legendary": "⭐️",
    "mythic": "🟥",
    "epic": "💎",
    "rare": "🔵",
    "common": "🟢",
}

# russian rarity names without emoji
RARITY_RU_SHORT = {
    "legendary": "Легендарная",
    "mythic": "Мифическая",
    "epic": "Эпическая",
    "rare": "Редкая",
    "common": "Обычная",
}

# order for sorting cards by rarity
RARITY_ORDER = {
    "legendary": 0,
    "mythic": 1,
    "epic": 2,
    "rare": 3,
    "common": 4,
}

TEAM_PAGE = 10

# order and labels for team slots
SLOT_ORDER = ["g", "d1", "d2", "f1", "f2", "f3", "b1", "b2", "b3"]
SLOT_LABELS = {
    "g": "🥅 G",
    "d1": "🛡 D1",
    "d2": "🛡 D2",
    "f1": "🚀 F1",
    "f2": "🚀 F2",
    "f3": "🚀 F3",
    "b1": "🪑 Запас1",
    "b2": "🪑 Запас2",
    "b3": "🪑 Запас3",
}

# mapping from slot id to storage location
SLOT_MAP = {
    "g": ("lineup", 0),
    "d1": ("lineup", 1),
    "d2": ("lineup", 2),
    "f1": ("lineup", 3),
    "f2": ("lineup", 4),
    "f3": ("lineup", 5),
    "b1": ("bench", 0),
    "b2": ("bench", 1),
    "b3": ("bench", 2),
}

# filtering for card positions by slot
SLOT_FILTER = {
    "g": "G",
    "d1": "D",
    "d2": "D",
    "f1": "F",
    "f2": "F",
    "f3": "F",
    "b1": "ANY",
    "b2": "ANY",
    "b3": "ANY",
}


def get_card_name(card_id: int) -> str:
    conn = db.get_db()
    cur = conn.cursor()
    cur.execute("SELECT name FROM cards WHERE id=?", (card_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else "?"


async def show_my_team(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    team = db.get_team(user_id)
    if not team:
        await update.message.reply_text("Команда не создана. Используй /team")
        return
    cards = {c["id"]: c for c in await get_user_cards(user_id)}
    lineup = [cards[cid] for cid in team.get("lineup", []) if cid in cards]
    bench = [cards[cid] for cid in team.get("bench", []) if cid in cards]

    avg_points = round(sum(c.get("points", 0) for c in lineup) / len(lineup)) if lineup else 0

    lines = [f"<b>{team['name']}</b> 🏒 (средние очки: {avg_points})", "👥 Основной состав:"]
    if lineup:
        for card in lineup:
            pos = card.get("pos", "")
            pos_icon = POSITION_EMOJI.get(pos, "")
            rarity = card.get("rarity", "common")
            rarity_emoji = RARITY_EMOJI.get(rarity, "")
            rarity_ru = RARITY_RU_SHORT.get(rarity, rarity)
            points = int(card.get("points", 0))
            lines.append(f"{pos_icon} <b>{card['name']}</b>")
            lines.append(f"Очки: {points}, {rarity_emoji} {rarity_ru}, {pos}")
            lines.append("")
    else:
        lines.append("—")

    lines.append("🪑 Запас:")
    if bench:
        for card in bench:
            pos = card.get("pos", "")
            pos_icon = POSITION_EMOJI.get(pos, "")
            rarity = card.get("rarity", "common")
            rarity_emoji = RARITY_EMOJI.get(rarity, "")
            rarity_ru = RARITY_RU_SHORT.get(rarity, rarity)
            points = int(card.get("points", 0))
            lines.append(f"{pos_icon} <b>{card['name']}</b>")
            lines.append(f"Очки: {points}, {rarity_emoji} {rarity_ru}, {pos}")
            lines.append("")
    else:
        lines.append("—")

    text = "\n".join(lines)
    buttons = [
        InlineKeyboardButton("✏️ Изменить", callback_data="team_edit"),
        InlineKeyboardButton("📝 Переименовать", callback_data="team_rename"),
    ]
    markup = InlineKeyboardMarkup([buttons])
    await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")


async def create_team(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if db.get_team(user_id):
        await show_my_team(update, context)
        return
    buttons = [
        [InlineKeyboardButton("🆕 Создать команду", callback_data="team_create")],
        [InlineKeyboardButton("📋 Назад", callback_data="team_cancel")],
    ]
    markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text(
        "У тебя ещё нет команды.", reply_markup=markup
    )


async def team_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tb = context.user_data.get("team_build")
    if not tb:
        return
    if tb.get("step") == "name":
        name = update.message.text.strip()[:30]
        if not (3 <= len(name) <= 8):
            await update.message.reply_text("Название должно быть от 3 до 8 символов, попробуйте снова:")
            return
        if db.team_name_taken(name, update.effective_user.id):
            await update.message.reply_text("Такое имя уже используется. Попробуйте другое.")
            return
        tb["name"] = name
        tb["step"] = "slots"
        tb["lineup"] = [None] * 6
        tb["bench"] = [None] * 3
        tb["page"] = 0
        context.user_data["team_build"] = tb
        await send_team_page(update.message.chat_id, update.effective_user.id, context)
    elif tb.get("step") == "rename":
        name = update.message.text.strip()[:30]
        if not (3 <= len(name) <= 8):
            await update.message.reply_text("Название должно быть от 3 до 8 символов, попробуйте снова:")
            return
        if db.team_name_taken(name, update.effective_user.id):
            await update.message.reply_text("Такое имя уже используется. Попробуйте другое.")
            return
        team = db.get_team(update.effective_user.id)
        if team:
            db.save_team(update.effective_user.id, name, team.get("lineup", []), team.get("bench", []))
        context.user_data.pop("team_build", None)
        await update.message.reply_text(f"Команда переименована в '{name}'")
        await show_my_team(update, context)


async def send_team_page(chat_id, user_id, context, edit=False, message_id=None):
    tb = context.user_data.get("team_build", {})
    step = tb.get("step")
    page = tb.get("page", 0)
    cards = {c["id"]: c for c in await get_user_cards(user_id)}

    if not cards:
        await context.bot.send_message(
            chat_id=chat_id,
            text="У вас пока нет карт, получите их командой /pack",
        )
        context.user_data.pop("team_build", None)
        return

    if step == "select_card":
        slot = tb.get("slot")
        list_name, idx = SLOT_MAP.get(slot, ("lineup", 0))
        current = tb.get(list_name, [None])[idx]
        selected_ids = set(x for x in tb.get("lineup", []) + tb.get("bench", []) if x)
        selected_ids.discard(current)
        filtered = []
        for c in cards.values():
            if c["id"] in selected_ids:
                continue
            pos = (c.get("pos") or "").upper()
            flt = SLOT_FILTER.get(slot)
            if flt == "G" and "G" not in pos:
                continue
            if flt == "D" and "D" not in pos:
                continue
            if flt == "F" and "G" in pos:
                continue
            filtered.append(c)

        filtered.sort(
            key=lambda c: (
                RARITY_ORDER.get(c.get("rarity", "common"), 99),
                c.get("name", ""),
            )
        )

        ids = [c["id"] for c in filtered]
        total_pages = max(1, (len(ids) + TEAM_PAGE - 1) // TEAM_PAGE)
        page = max(0, min(page, total_pages - 1))
        page_cards = ids[page * TEAM_PAGE : (page + 1) * TEAM_PAGE]

        buttons = []
        if current:
            buttons.append([InlineKeyboardButton("❌ Убрать", callback_data="team_clear")])
        for cid in page_cards:
            card = cards[cid]
            emoji = RARITY_EMOJI.get(card.get("rarity", "common"), "")
            text_btn = f"{card['name']} ({card.get('pos','?')}) {emoji} {int(card.get('points',0))}"
            buttons.append([InlineKeyboardButton(text_btn, callback_data=f"team_pick_{cid}")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀️", callback_data="team_prev"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("▶️", callback_data="team_next"))
        nav.append(InlineKeyboardButton("↩️ Назад", callback_data="team_back"))
        markup = InlineKeyboardMarkup(buttons + [nav])
        text = f"Выберите карту для слота {SLOT_LABELS.get(slot,'')}"
        if edit and message_id:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=markup,
            )
        else:
            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)
        return

    # default: show slots
    lineup = tb.get("lineup", [None] * 6)
    bench = tb.get("bench", [None] * 3)
    text_lines = ["Нажми на слот и выбери карту:"]
    buttons = []
    for slot in SLOT_ORDER:
        list_name, idx = SLOT_MAP[slot]
        card_id = lineup[idx] if list_name == "lineup" else bench[idx]
        name = cards.get(card_id, {}).get("name") if card_id else "—"
        label = f"{SLOT_LABELS[slot]}: {name}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"team_slot_{slot}")])

    controls = [
        [InlineKeyboardButton("♻️ Сбросить", callback_data="team_reset")],
        [InlineKeyboardButton("✅ Готово", callback_data="team_done")],
    ]
    markup = InlineKeyboardMarkup(buttons + controls)
    text = "\n".join(text_lines)
    if edit and message_id:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=markup,
        )
    else:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)


async def team_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tb = context.user_data.get("team_build")
    data = query.data

    # map direction callbacks to attack direction values
    dir_map = DIR_MAP

    if data == "team_edit":
        team = db.get_team(query.from_user.id)
        if team:
            lineup = team.get("lineup", [])
            bench = team.get("bench", [])
            lineup += [None] * (6 - len(lineup))
            bench += [None] * (3 - len(bench))
            context.user_data["team_build"] = {
                "step": "slots",
                "name": team.get("name", "Team"),
                "lineup": lineup,
                "bench": bench,
                "page": 0,
            }
            await send_team_page(
                query.message.chat_id,
                query.from_user.id,
                context,
                edit=True,
                message_id=query.message.message_id,
            )
        return
    if data == "team_rename":
        context.user_data["team_build"] = {"step": "rename"}
        await query.edit_message_text("Введите новое название команды (3-8 символов):")
        return
    if data == "team_create":
        context.user_data["team_build"] = {"step": "name"}
        await query.edit_message_text("Введите название команды (3-8 символов):")
        return
    if data == "team_cancel":
        context.user_data.pop("team_build", None)
        await query.message.delete()
        return
    if not tb:
        return

    if tb.get("step") == "select_card":
        if data == "team_next":
            tb["page"] += 1
        elif data == "team_prev":
            tb["page"] = max(0, tb.get("page", 0) - 1)
        elif data == "team_back":
            tb["step"] = "slots"
            tb.pop("slot", None)
            tb["page"] = 0
        elif data == "team_clear":
            slot = tb.get("slot")
            list_name, idx = SLOT_MAP.get(slot, ("lineup", 0))
            tb[list_name][idx] = None
            tb["step"] = "slots"
            tb.pop("slot", None)
            tb["page"] = 0
        elif data.startswith("team_pick_"):
            cid = int(data.split("_")[2])
            slot = tb.get("slot")
            list_name, idx = SLOT_MAP.get(slot, ("lineup", 0))
            tb[list_name][idx] = cid
            tb["step"] = "slots"
            tb.pop("slot", None)
            tb["page"] = 0
    else:  # slot selection step
        if data.startswith("team_slot_"):
            tb["slot"] = data.split("_")[2]
            tb["step"] = "select_card"
            tb["page"] = 0
        elif data == "team_reset":
            tb["lineup"] = [None] * 6
            tb["bench"] = [None] * 3
            tb["page"] = 0
        elif data == "team_done":
            lineup = [c for c in tb.get("lineup", []) if c]
            bench = [c for c in tb.get("bench", []) if c]
            db.save_team(query.from_user.id, tb.get("name", "Team"), lineup, bench)
            context.user_data.pop("team_build", None)
            await query.edit_message_text(
                f"Команда '{tb.get('name','Team')}' сохранена."
            )
            return

    await send_team_page(
        query.message.chat_id,
        query.from_user.id,
        context,
        edit=True,
        message_id=query.message.message_id,
    )

async def start_fight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начать интерактивный бой против бота."""
    from helpers.admin_utils import banned_users
    if update.effective_user.id in banned_users:
        await update.message.reply_text("🚫 Вы заблокированы в боте.")
        return
    context.user_data["fight_mode"] = "pve"
    user_id = update.effective_user.id
    team_data = db.get_team(user_id)
    team_name = team_data["name"] if team_data else "Team1"
    team1 = await _build_team(user_id, team_data["lineup"] if team_data else None)
    team2 = await _build_team(0)
    session = BattleSession(team1, team2, name1=team_name, name2="Bot")
    controller = BattleController(session)
    context.user_data["battle_state"] = {"controller": controller}
    keyboard = [
        [InlineKeyboardButton("⚡️ Играть агрессивно", callback_data="battle_aggressive")],
        [InlineKeyboardButton("🛡 Играть осторожно", callback_data="battle_defensive")],
        [InlineKeyboardButton("🎯 Держать темп", callback_data="battle_balanced")],
    ]
    await update.message.reply_text(
        "⏱ Первый период. Выбери установку:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def start_duel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Join PvP queue without tactic selection."""
    from helpers.admin_utils import banned_users
    if update.effective_user.id in banned_users:
        await update.message.reply_text("🚫 Вы заблокированы в боте.")
        return
    context.user_data["fight_mode"] = "pvp"
    user = update.effective_user
    user_id = user.id
    tactic = "balanced"


    team_data = db.get_team(user_id)
    team_name = team_data["name"] if team_data else "Team1"
    team = await _build_team(user_id, team_data["lineup"] if team_data else None)

    existing = PVP_QUEUE.get(user_id)
    if existing and existing.get("reserved"):
        await update.message.reply_text("Ожидание соперника...")
        return

    entry = {
        "team": team,
        "tactic": tactic,
        "name": team_name,
        "username": user.username or str(user_id),
        "reserved": True,
        "created": time.time(),
    }
    PVP_QUEUE[user_id] = entry

    opponents = [(uid, data) for uid, data in PVP_QUEUE.items() if uid != user_id]
    if not opponents:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отменить", callback_data="duel_cancel")]])
        await update.message.reply_text("Ждём второго игрока...", reply_markup=markup)
    elif len(opponents) == 1:
        opp_id, opp_data = opponents[0]
        PVP_QUEUE.pop(opp_id, None)
        PVP_QUEUE.pop(user_id, None)
        await _start_pvp_duel(user_id, opp_id, team, opp_data["team"], team_name, opp_data["name"], context)
    else:
        buttons = [
            [InlineKeyboardButton(data.get("username", str(uid)), callback_data=f"challenge_{uid}")]
            for uid, data in opponents
        ]
        buttons.append([InlineKeyboardButton("❌ Отменить", callback_data="duel_cancel")])
        await update.message.reply_text("Выбери соперника:", reply_markup=InlineKeyboardMarkup(buttons))

async def duel_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    opponents = [(uid, data) for uid, data in PVP_QUEUE.items() if uid != user_id]
    if not opponents:
        await update.message.reply_text("Никто не ожидает дуэли.")
        return
    buttons = [[InlineKeyboardButton(data.get("username", str(uid)), callback_data=f"challenge_{uid}")] for uid, data in opponents]
    buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="duel_cancel")])
    await update.message.reply_text("Выбери соперника:", reply_markup=InlineKeyboardMarkup(buttons))

async def _build_team(user_id, ids=None):
    cards = await get_user_cards(user_id)
    level = db.get_xp_level(user_id)[1] if user_id else 1
    team = []
    if ids:
        id_set = list(ids)
        for cid in id_set:
            card = next((c for c in cards if c["id"] == cid), None)
            if card:
                team.append({
                    "id": card["id"],
                    "name": card["name"],
                    "pos": card.get("pos", ""),
                    "country": card.get("country", ""),
                    "born": str(card.get("born", "")),
                    "weight": str(card.get("weight", "")),
                    "rarity": card.get("rarity", "common"),
                    "points": float(card.get("points", 50)),
                    "owner_level": level,
                })
        cards = [c for c in cards if c["id"] not in id_set]
    random.shuffle(cards)
    for card in cards[: max(0, 6 - len(team))]:
        team.append({
            "id": card["id"],
            "name": card["name"],
            "pos": card.get("pos", ""),
            "country": card.get("country", ""),
            "born": str(card.get("born", "")),
            "weight": str(card.get("weight", "")),
            "rarity": card.get("rarity", "common"),
            "points": float(card.get("points", 50)),
            "owner_level": level,
        })
    # если нет карт, добавляем случайные
    while len(team) < 6:
        card = await get_random_card()
        team.append({
            "id": card["id"],
            "name": card["name"],
            "pos": card.get("pos", ""),
            "country": card.get("country", ""),
            "born": str(card.get("born", "")),
            "weight": str(card.get("weight", "")),
            "rarity": card.get("rarity", "common"),
            "points": float(card.get("points", 50)),
            "owner_level": level,
        })
    return team



async def _start_pvp_duel(uid1: int, uid2: int, team1, team2, name1: str, name2: str, context: ContextTypes.DEFAULT_TYPE):
    """Initialize interactive PvP duel using ``BattleController``."""
    session = BattleSession(team1, team2, name1=name1, name2=name2)
    controller = BattleController(session)
    duel_key = tuple(sorted((uid1, uid2)))
    ACTIVE_DUELS[duel_key] = {"controller": controller, "choices": {}, "users": (uid1, uid2)}
    DUEL_USERS[uid1] = duel_key
    DUEL_USERS[uid2] = duel_key
    keyboard = [
        [InlineKeyboardButton("⚡️ Играть агрессивно", callback_data="battle_aggressive")],
        [InlineKeyboardButton("🛡 Играть осторожно", callback_data="battle_defensive")],
        [InlineKeyboardButton("🎯 Держать темп", callback_data="battle_balanced")],
    ]
    markup = InlineKeyboardMarkup(keyboard)
    await _safe_send_message(context.bot, uid1, "⏱ Первый период. Выбери установку:", reply_markup=markup)
    await _safe_send_message(context.bot, uid2, "⏱ Первый период. Выбери установку:", reply_markup=markup)


async def _prompt_pvp_phase(state: dict, context: ContextTypes.DEFAULT_TYPE):
    """Send tactic selection message for the current phase to both players."""
    controller: BattleController = state["controller"]

    phase = controller.phase
    log = controller.session.log
    score = controller.session.score

    def summary(lines):
        return "\n".join(lines[-3:]) if lines else ""

    if phase == "p2":
        text = format_period_summary(controller.session)
        keyboard = [
            [InlineKeyboardButton("🔁 Сделать замену", callback_data="battle_change")],
            [InlineKeyboardButton("⚔️ Уйти в атаку", callback_data="battle_attack")],
            [InlineKeyboardButton("🛡 Укрепить оборону", callback_data="battle_defense")],
        ]
    elif phase == "p3":
        text = format_period_summary(controller.session)
        keyboard = [
            [InlineKeyboardButton("⚡️ Давить до конца", callback_data="battle_pressure")],
            [InlineKeyboardButton("⛔️ Уйти в оборону", callback_data="battle_hold")],
            [InlineKeyboardButton("♻️ Играть на ничью", callback_data="battle_tie")],
        ]
    elif phase == "ot":
        text = (
            f"{summary(log)}\nСчёт: {score['team1']} - {score['team2']}\n"
            "🟰 Ничья! Овертайм:"
        )
        keyboard = [
            [InlineKeyboardButton("⚔️ Давим до гола!", callback_data="battle_ot_attack")],
            [InlineKeyboardButton("🩻 Осторожно — ловим ошибку", callback_data="battle_ot_careful")],
        ]
    else:
        return

    markup = InlineKeyboardMarkup(keyboard)
    for uid in state["users"]:
        await _safe_send_message(context.bot, uid, text, reply_markup=markup, parse_mode="HTML")




async def tactic_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tactic = TACTICS.get(query.data, "balanced")
    mode = context.user_data.get("fight_mode", "pve")
    user_id = query.from_user.id
    team_data = db.get_team(user_id)
    team_name = team_data["name"] if team_data else "Team1"
    team = await _build_team(user_id, team_data["lineup"] if team_data else None)
    if mode == "pvp":
        existing = PVP_QUEUE.get(user_id)
        if existing and existing.get("reserved"):
            await query.edit_message_text("Ожидание соперника...")
            return
        entry = {
            "team": team,
            "tactic": tactic,
            "name": team_name,
            "username": query.from_user.username or str(user_id),
            "reserved": True,
            "created": time.time(),
        }
        PVP_QUEUE[user_id] = entry
        opponents = [(uid, data) for uid, data in PVP_QUEUE.items() if uid != user_id]
        if not opponents:
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отменить", callback_data="duel_cancel")]])
            await query.edit_message_text("Ждём второго игрока...", reply_markup=markup)
        elif len(opponents) == 1:
            opp_id, opp_data = opponents[0]
            PVP_QUEUE.pop(opp_id, None)
            PVP_QUEUE.pop(user_id, None)
            await _start_pvp_duel(user_id, opp_id, team, opp_data["team"], team_name, opp_data["name"], context)
        else:
            buttons = [
                [InlineKeyboardButton(data.get("username", str(uid)), callback_data=f"challenge_{uid}")]
                for uid, data in opponents
            ]
            buttons.append([InlineKeyboardButton("❌ Отменить", callback_data="duel_cancel")])
            await query.edit_message_text("Выбери соперника:", reply_markup=InlineKeyboardMarkup(buttons))
    else:
        team1 = team
        team2 = await _build_team(0)
        tactic2 = random.choice(list(TACTICS.values()))
        session = BattleSession(team1, team2, tactic1=tactic, tactic2=tactic2, name1=team_name, name2="Bot")
        controller = BattleController(session)
        result = await asyncio.to_thread(controller.auto_play)
        db.save_battle_result(user_id, "Bot", result)
        xp_gain, lvl, leveled = await apply_xp(user_id, result, True, context)
        summary = format_final_summary(session, result, xp_gain, lvl, leveled)
        await context.bot.send_message(
            user_id,
            summary,
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("⚙ Управление командой", callback_data="open_team")],
                    [InlineKeyboardButton("🏠 Вернуться в меню", callback_data="menu_back")],
                ]
            ),
            parse_mode="HTML",
        )


async def battle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle step-by-step battle choices for PvE matches."""
    query = update.callback_query
    await query.answer()
    if query.from_user.id in DUEL_USERS:
        await _handle_pvp_battle(update, context)
        return
    state = context.user_data.get("battle_state")
    if not state:
        return
    controller: BattleController = state.get("controller")
    if not controller:
        return

    data = query.data

    # map direction callbacks to attack direction values
    dir_map = DIR_MAP

    def summary(lines):
        return "\n".join(lines[-3:]) if lines else ""

    phase = controller.phase
    log = controller.session.log
    score = controller.session.score

    # handle direction choice
    if data in dir_map:
        context.user_data["attack_dir"] = dir_map[data]
        tactic = context.user_data.pop("pending_tactic", "balanced")
        prev_phase = context.user_data.pop("pending_phase", phase)
        controller.session.user_attack_dir = context.user_data["attack_dir"]
        controller.step(tactic, random.choice(list(TACTICS.values())))
        context.user_data.pop("attack_dir", None)

        if prev_phase == "p1":
            text = format_period_summary(controller.session)
            keyboard = [
                [InlineKeyboardButton("🔁 Сделать замену", callback_data="battle_change")],
                [InlineKeyboardButton("⚔️ Уйти в атаку", callback_data="battle_attack")],
                [InlineKeyboardButton("🛡 Укрепить оборону", callback_data="battle_defense")],
            ]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        elif prev_phase == "p2":
            text = format_period_summary(controller.session)
            keyboard = [
                [InlineKeyboardButton("⚡️ Давить до конца", callback_data="battle_pressure")],
                [InlineKeyboardButton("⛔️ Уйти в оборону", callback_data="battle_hold")],
                [InlineKeyboardButton("♻️ Играть на ничью", callback_data="battle_tie")],
            ]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        elif prev_phase == "p3":
            if controller.phase == "ot":
                text = (
                    f"{summary(controller.session.log)}\nСчёт: {controller.session.score['team1']} - {controller.session.score['team2']}\n"
                    "🟰 Ничья! Овертайм:"
                )
                keyboard = [
                    [InlineKeyboardButton("⚔️ Давим до гола!", callback_data="battle_ot_attack")],
                    [InlineKeyboardButton("🩻 Осторожно — ловим ошибку", callback_data="battle_ot_careful")],
                ]
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            else:
                result = controller.session.finish()
                xp_gain, lvl, up = await apply_xp(query.from_user.id, result, True, context)
                summary_text = format_final_summary(controller.session, result, xp_gain, lvl, up)
                await query.edit_message_text(
                    summary_text,
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [InlineKeyboardButton("⚙ Управление командой", callback_data="open_team")],
                            [InlineKeyboardButton("🏠 Вернуться в меню", callback_data="menu_back")],
                        ]
                    ),
                    parse_mode="HTML",
                )
                state.clear()
        elif prev_phase == "ot":
            result = controller.session.finish()
            xp_gain, lvl, up = await apply_xp(query.from_user.id, result, True, context)
            summary_text = format_final_summary(controller.session, result, xp_gain, lvl, up)
            await query.edit_message_text(
                summary_text,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("⚙ Управление командой", callback_data="open_team")],
                        [InlineKeyboardButton("🏠 Вернуться в меню", callback_data="menu_back")],
                    ]
                ),
                parse_mode="HTML",
            )
            state.clear()
        return

    if phase == "p1":
        tactic = data.split("_")[1]
        context.user_data["pending_tactic"] = tactic
        context.user_data["pending_phase"] = phase
        keyboard = [
            [InlineKeyboardButton("⬅ Слева", callback_data="dir_left")],
            [InlineKeyboardButton("⬆ По центру", callback_data="dir_center")],
            [InlineKeyboardButton("➡ Справа", callback_data="dir_right")],
        ]
        await query.edit_message_text("Выбери направление атаки", reply_markup=InlineKeyboardMarkup(keyboard))
    elif phase == "p2":
        if data == "battle_change":
            tactic = "balanced"
        elif data == "battle_attack":
            tactic = "aggressive"
        else:
            tactic = "defensive"
        context.user_data["pending_tactic"] = tactic
        context.user_data["pending_phase"] = phase
        keyboard = [
            [InlineKeyboardButton("⬅ Слева", callback_data="dir_left")],
            [InlineKeyboardButton("⬆ По центру", callback_data="dir_center")],
            [InlineKeyboardButton("➡ Справа", callback_data="dir_right")],
        ]
        await query.edit_message_text("Выбери направление атаки", reply_markup=InlineKeyboardMarkup(keyboard))
    elif phase == "p3":
        if data == "battle_pressure":
            tactic = "aggressive"
        elif data == "battle_hold":
            tactic = "defensive"
        else:
            tactic = "balanced"
        context.user_data["pending_tactic"] = tactic
        context.user_data["pending_phase"] = phase
        keyboard = [
            [InlineKeyboardButton("⬅ Слева", callback_data="dir_left")],
            [InlineKeyboardButton("⬆ По центру", callback_data="dir_center")],
            [InlineKeyboardButton("➡ Справа", callback_data="dir_right")],
        ]
        await query.edit_message_text("Выбери направление атаки", reply_markup=InlineKeyboardMarkup(keyboard))
    elif phase == "ot":
        tactic = "aggressive" if data == "battle_ot_attack" else "defensive"
        context.user_data["pending_tactic"] = tactic
        context.user_data["pending_phase"] = phase
        keyboard = [
            [InlineKeyboardButton("⬅ Слева", callback_data="dir_left")],
            [InlineKeyboardButton("⬆ По центру", callback_data="dir_center")],
            [InlineKeyboardButton("➡ Справа", callback_data="dir_right")],
        ]
        await query.edit_message_text("Выбери направление атаки", reply_markup=InlineKeyboardMarkup(keyboard))


async def _handle_pvp_battle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    uid = query.from_user.id
    duel_key = DUEL_USERS.get(uid)
    state = ACTIVE_DUELS.get(duel_key)
    if not state:
        return

    mapping = {
        "battle_aggressive": "aggressive",
        "battle_defensive": "defensive",
        "battle_balanced": "balanced",
        "battle_change": "balanced",
        "battle_attack": "aggressive",
        "battle_defense": "defensive",
        "battle_pressure": "aggressive",
        "battle_hold": "defensive",
        "battle_tie": "balanced",
        "battle_ot_attack": "aggressive",
        "battle_ot_careful": "defensive",
    }

    tactic = mapping.get(query.data)
    if tactic is None:
        return

    state["choices"][uid] = tactic
    await query.edit_message_text("Ожидание соперника...")

    if len(state["choices"]) < 2:
        return

    uid1, uid2 = state["users"]
    t1 = state["choices"].pop(uid1)
    t2 = state["choices"].pop(uid2)
    controller: BattleController = state["controller"]
    controller.step(t1, t2)

    if controller.phase == "end":
        result = controller.session.finish()
        db.save_battle_result(uid1, str(uid2), result)
        xp1, lvl1, up1 = await apply_xp(uid1, result, False, context)
        opp_result = result.copy()
        if result.get("winner") == "team1":
            opp_result["winner"] = "team2"
        elif result.get("winner") == "team2":
            opp_result["winner"] = "team1"
        opp_result["str_gap"] = -result.get("str_gap", 0.0)
        xp2, lvl2, up2 = await apply_xp(uid2, opp_result, False, context)
        summary1 = format_final_summary(controller.session, result, xp1, lvl1, up1)
        summary2 = format_final_summary(controller.session, opp_result, xp2, lvl2, up2)
        await _safe_send_message(
            context.bot,
            uid1,
            summary1,
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("⚙ Управление командой", callback_data="open_team")],
                    [InlineKeyboardButton("🏠 Вернуться в меню", callback_data="menu_back")],
                ]
            ),
            parse_mode="HTML",
        )
        await _safe_send_message(
            context.bot,
            uid2,
            summary2,
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("⚙ Управление командой", callback_data="open_team")],
                    [InlineKeyboardButton("🏠 Вернуться в меню", callback_data="menu_back")],
                ]
            ),
            parse_mode="HTML",
        )
        DUEL_USERS.pop(uid1, None)
        DUEL_USERS.pop(uid2, None)
        ACTIVE_DUELS.pop(duel_key, None)
    else:
        await _prompt_pvp_phase(state, context)


async def duel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    if data == "duel_cancel":
        PVP_QUEUE.pop(user_id, None)
        await query.edit_message_text("Поиск дуэли отменён.")
        return
    if data.startswith("challenge_"):
        opp_id = int(data.split("_")[1])
        if opp_id not in PVP_QUEUE or user_id not in PVP_QUEUE:
            await query.answer("Игрок недоступен", show_alert=True)
            return
        opp_data = PVP_QUEUE.pop(opp_id)
        my_data = PVP_QUEUE.pop(user_id)
        await _start_pvp_duel(
            user_id,
            opp_id,
            my_data["team"],
            opp_data["team"],
            my_data["name"],
            opp_data["name"],
            context,
        )
        return

async def show_battle_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    battles = db.get_battle_history(user_id)
    if not battles:
        await update.message.reply_text("История боёв пуста.")
        return
    parts = []
    for ts, opponent, res, s1, s2, mvp in battles:
        parts.append(f"🆚 {opponent}\n📅 {ts}\nСчёт: {s1} : {s2}\n🏆 Победа: {res}\n⭐️ MVP: {mvp}")
    await update.message.reply_text("\n\n".join(parts), reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Вернуться в меню", callback_data="menu_back")]
    ]))


@admin_only
async def rename_player(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show list of players for renaming."""
    players = db.get_all_players()
    if not players:
        await update.message.reply_text("Игроки не найдены.")
        return
    buttons = [
        [InlineKeyboardButton(f"👤 {name}", callback_data=f"rename_select:{pid}")]
        for pid, name in players
    ]
    markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text(
        "Выберите игрока:", reply_markup=markup
    )


async def rename_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    if not query.data.startswith("rename_select:"):
        return
    pid = int(query.data.split(":")[1])
    name = get_card_name(pid)
    context.user_data["rename_player"] = {"id": pid}
    await query.edit_message_text(f"✍️ Введи новое имя для {name}:")


async def rename_player_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("rename_player")
    if not state:
        return
    if not is_admin(update.effective_user.id):
        return
    pid = state.get("id")
    new_name = update.message.text.strip()
    db.update_player_name(pid, new_name)
    context.user_data.pop("rename_player", None)
    from bot import refresh_card_cache
    refresh_card_cache(pid)
    await update.message.reply_text(f"✅ Игрок теперь известен как {new_name}!")


def cleanup_pvp_queue():
    """Remove stale entries from PVP queue."""
    now = time.time()
    for uid in list(PVP_QUEUE.keys()):
        created = PVP_QUEUE[uid].get("created", now)
        if now - created > PVP_TTL:
            PVP_QUEUE.pop(uid, None)
