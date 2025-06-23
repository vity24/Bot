from collections import OrderedDict
import random
import asyncio
import re
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from battle import BattleSession
import db
from helpers.leveling import level_from_xp, xp_to_next, calc_battle_xp

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
            "INSERT INTO inventory (user_id, card_id, time_got) VALUES (?, ?, strftime('%s','now'))",
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
    if new_lvl > old_lvl:
        await grant_level_reward(uid, new_lvl, context)
    if xp_gain:
        await context.bot.send_message(uid, f"➕ +{xp_gain} XP", parse_mode="Markdown")


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

LOG_LINES_PER_PAGE = 15
PVP_QUEUE = OrderedDict()

TACTICS = {
    "tactic_aggressive": "aggressive",
    "tactic_defensive": "defensive",
    "tactic_balanced": "balanced",
}

# simple mapping of rarity to emoji for buttons
RARITY_EMOJI = {
    "legendary": "⭐️",
    "mythic": "🟥",
    "epic": "💎",
    "rare": "🔵",
    "common": "🟢",
}

TEAM_PAGE = 10


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
    lineup_names = [get_card_name(cid) for cid in team.get("lineup", [])]
    bench_names = [get_card_name(cid) for cid in team.get("bench", [])]
    text = (
        f"{team['name']}\n"
        f"🏒 {', '.join(lineup_names) if lineup_names else '—'}\n"
        f"🪑 {', '.join(bench_names) if bench_names else '—'}"
    )
    buttons = [
        InlineKeyboardButton("✏️ Изменить", callback_data="team_edit"),
        InlineKeyboardButton("📝 Переименовать", callback_data="team_rename"),
    ]
    markup = InlineKeyboardMarkup([buttons])
    await update.message.reply_text(text, reply_markup=markup)


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
        tb["step"] = "select"
        tb["selected"] = []
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
    page = tb.get("page", 0)
    selected = tb.get("selected", [])
    cards = {c["id"]: c for c in await get_user_cards(user_id)}
    if not cards:
        await context.bot.send_message(
            chat_id=chat_id,
            text="У вас пока нет карт, получите их командой /pack",
        )
        context.user_data.pop("team_build", None)
        return
    ids = list(cards.keys())
    total_pages = (len(ids) + TEAM_PAGE - 1) // TEAM_PAGE
    page_cards = ids[page * TEAM_PAGE:(page + 1) * TEAM_PAGE]
    buttons = []
    for cid in page_cards:
        card = cards[cid]
        emoji = RARITY_EMOJI.get(card.get("rarity", "common"), "")
        mark = " ✅" if cid in selected else ""
        text_btn = f"{mark}{card['name']} ({card.get('pos','?')}) {emoji} {int(card.get('points',0))}"
        buttons.append([InlineKeyboardButton(text_btn, callback_data=f"team_sel_{cid}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data="team_prev"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("▶️", callback_data="team_next"))
    nav.append(InlineKeyboardButton("Готово", callback_data="team_done"))
    markup = InlineKeyboardMarkup(buttons + [nav])
    text = (
        f"Выбери до 9 карт. Сейчас выбрано: {len(selected)}\n"
        f"Стартовых: {min(len(selected),6)}, запас: {max(0,len(selected)-6)}"
    )
    if edit and message_id:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup)
    else:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)


async def team_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tb = context.user_data.get("team_build")
    data = query.data
    if data == "team_edit":
        team = db.get_team(query.from_user.id)
        if team:
            context.user_data["team_build"] = {
                "step": "select",
                "name": team.get("name", "Team"),
                "selected": team.get("lineup", []) + team.get("bench", []),
                "page": 0,
            }
            await send_team_page(query.message.chat_id, query.from_user.id, context, edit=True, message_id=query.message.message_id)
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
    if data == "team_next":
        tb["page"] += 1
    elif data == "team_prev":
        tb["page"] = max(0, tb.get("page", 0) - 1)
    elif data.startswith("team_sel_"):
        cid = int(data.split("_")[2])
        if cid in tb["selected"]:
            tb["selected"].remove(cid)
        else:
            if len(tb["selected"]) >= 9:
                await query.answer("Можно выбрать не более 9 карт", show_alert=True)
                return
            tb["selected"].append(cid)
    elif data == "team_done":
        lineup = tb["selected"][:6]
        bench = tb["selected"][6:]
        db.save_team(query.from_user.id, tb.get("name", "Team"), lineup, bench)
        context.user_data.pop("team_build", None)
        note = "Недостающие места будут заполнены случайными картами в бою." if len(lineup) < 6 else ""
        await query.edit_message_text(
            f"Команда '{tb.get('name','Team')}' сохранена. {note}"
        )
        return
    await send_team_page(query.message.chat_id, query.from_user.id, context, edit=True, message_id=query.message.message_id)

async def start_fight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["fight_mode"] = "pve"
    keyboard = [
        [InlineKeyboardButton("⚔️ Агрессивная", callback_data="tactic_aggressive")],
        [InlineKeyboardButton("🛡️ Оборонительная", callback_data="tactic_defensive")],
        [InlineKeyboardButton("⚖️ Сбалансированная", callback_data="tactic_balanced")],
    ]
    await update.message.reply_text("Выбери тактику:", reply_markup=InlineKeyboardMarkup(keyboard))

async def start_duel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["fight_mode"] = "pvp"
    keyboard = [
        [InlineKeyboardButton("⚔️ Агрессивная", callback_data="tactic_aggressive")],
        [InlineKeyboardButton("🛡️ Оборонительная", callback_data="tactic_defensive")],
        [InlineKeyboardButton("⚖️ Сбалансированная", callback_data="tactic_balanced")],
    ]
    await update.message.reply_text("Выбери тактику для дуэли:", reply_markup=InlineKeyboardMarkup(keyboard))

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

async def _run_battle(user_id, opponent_name, team1, team2, tactic1, tactic2, name1="Team1", name2="Team2"):
    session = BattleSession(team1, team2, tactic1=tactic1, tactic2=tactic2, name1=name1, name2=name2)
    result = await asyncio.to_thread(session.simulate)
    db.save_battle_result(user_id, opponent_name, result)
    return result


def _format_log_page(user_data):
    page = user_data.get("log_page", 0)
    log = user_data.get("log", [])
    score = user_data.get("score", {"team1": 0, "team2": 0})
    total_pages = max(1, (len(log) + LOG_LINES_PER_PAGE - 1) // LOG_LINES_PER_PAGE)
    header = f"<b>🏒 {score['team1']} : {score['team2']} | стр. {page + 1}/{total_pages}</b>"
    body_lines = log[page * LOG_LINES_PER_PAGE:(page + 1) * LOG_LINES_PER_PAGE]
    body = "\n".join(body_lines)
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("◀️", callback_data="log_prev"))
    if page < total_pages - 1:
        buttons.append(InlineKeyboardButton("▶️", callback_data="log_next"))
    buttons.append(InlineKeyboardButton("❌", callback_data="log_close"))
    markup = InlineKeyboardMarkup([buttons])
    return f"{header}\n{body}", markup


async def _start_log_view(user_id: int, result: dict, context: ContextTypes.DEFAULT_TYPE):
    ud = context.application.user_data.setdefault(user_id, {})
    ud.pop("log", None)
    ud.pop("log_page", None)
    ud.pop("score", None)
    ud["log"] = result.get("log", [])
    ud["score"] = result.get("score", {"team1": 0, "team2": 0})
    ud["log_page"] = 0
    text, markup = _format_log_page(ud)
    await context.bot.send_message(user_id, text or "Нет логов", reply_markup=markup, parse_mode="HTML")

async def tactic_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tactic = TACTICS.get(query.data, "balanced")
    mode = context.user_data.get("fight_mode", "pve")
    user_id = query.from_user.id
    # clear previous logs
    ud = context.application.user_data.setdefault(user_id, {})
    ud.pop("log", None)
    ud.pop("log_page", None)
    ud.pop("score", None)
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
            result = await _run_battle(user_id, str(opp_id), team, opp_data["team"], tactic, opp_data["tactic"], team_name, opp_data["name"])
            await apply_xp(user_id, result, False, context)
            opp_result = result.copy()
            if result.get("winner") == "team1":
                opp_result["winner"] = "team2"
            elif result.get("winner") == "team2":
                opp_result["winner"] = "team1"
            opp_result["str_gap"] = -result.get("str_gap", 0.0)
            await apply_xp(opp_id, opp_result, False, context)
            await _start_log_view(update.effective_user.id, result, context)
            await _start_log_view(opp_id, result, context)
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
        result = await _run_battle(user_id, "Bot", team1, team2, tactic, tactic2, team_name, "Bot")
        await apply_xp(user_id, result, True, context)
        await _start_log_view(update.effective_user.id, result, context)

async def show_log_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, markup = _format_log_page(context.user_data)
    await update.callback_query.edit_message_text(text or "Нет логов", reply_markup=markup, parse_mode="HTML")

async def log_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "log_prev":
        context.user_data["log_page"] = max(0, context.user_data.get("log_page", 0) - 1)
    elif query.data == "log_next":
        context.user_data["log_page"] = context.user_data.get("log_page", 0) + 1
    elif query.data == "log_close":
        context.user_data.pop("log", None)
        context.user_data.pop("log_page", None)
        context.user_data.pop("score", None)
        await query.message.delete()
        return
    await show_log_page(update, context)

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
        result = await _run_battle(
            user_id,
            str(opp_id),
            my_data["team"],
            opp_data["team"],
            my_data["tactic"],
            opp_data["tactic"],
            my_data["name"],
            opp_data["name"],
        )
        await apply_xp(user_id, result, False, context)
        opp_result = result.copy()
        if result.get("winner") == "team1":
            opp_result["winner"] = "team2"
        elif result.get("winner") == "team2":
            opp_result["winner"] = "team1"
        opp_result["str_gap"] = -result.get("str_gap", 0.0)
        await apply_xp(opp_id, opp_result, False, context)
        await _start_log_view(user_id, result, context)
        await _start_log_view(opp_id, result, context)
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
    await update.message.reply_text("\n\n".join(parts))
