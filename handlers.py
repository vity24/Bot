import random
import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from battle import BattleSession
import db


async def get_random_card():
    conn = db.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name, pos, country, born, weight, rarity, points FROM cards ORDER BY RANDOM() LIMIT 1")
    row = cur.fetchone()
    conn.close()
    if row:
        return dict(zip(["id","name","pos","country","born","weight","rarity","points"], row))
    return None

def get_user_cards(user_id):
    conn = db.get_db()
    cur = conn.cursor()
    cur.execute("SELECT card_id FROM inventory WHERE user_id=?", (user_id,))
    ids = [r[0] for r in cur.fetchall()]
    cards = []
    for cid in ids:
        cur.execute("SELECT id, name, pos, country, born, weight, rarity, points FROM cards WHERE id=?", (cid,))
        row = cur.fetchone()
        if row:
            cards.append(dict(zip(["id","name","pos","country","born","weight","rarity","points"], row)))
    conn.close()
    return cards
PVP_QUEUE = {}

TACTICS = {
    "tactic_aggressive": "aggressive",
    "tactic_defensive": "defensive",
    "tactic_balanced": "balanced",
}

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

async def _build_team(user_id):
    cards = get_user_cards(user_id)
    team = []
    random.shuffle(cards)
    for card in cards[:6]:
        team.append({
            "id": card["id"],
            "name": card["name"],
            "pos": card.get("pos", ""),
            "country": card.get("country", ""),
            "born": str(card.get("born", "")),
            "weight": str(card.get("weight", "")),
            "rarity": card.get("rarity", "common"),
            "points": float(card.get("points", 50)),
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
        })
    return team

async def _run_battle(user_id, opponent_name, team1, team2, tactic1, tactic2):
    session = BattleSession(team1, team2, tactic1=tactic1, tactic2=tactic2)
    result = await asyncio.to_thread(session.simulate)
    db.save_battle_result(user_id, opponent_name, result)
    return result

async def tactic_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tactic = TACTICS.get(query.data, "balanced")
    mode = context.user_data.get("fight_mode", "pve")
    user_id = query.from_user.id
    if mode == "pvp":
        team = await _build_team(user_id)
        if PVP_QUEUE:
            opp_id, opp_data = PVP_QUEUE.popitem()
            opponent_team = opp_data["team"]
            tactic2 = opp_data["tactic"]
            result = await _run_battle(user_id, str(opp_id), team, opponent_team, tactic, tactic2)
            context.user_data["log"] = result["log"]
            context.user_data["log_page"] = 0
            await show_log_page(update, context)
            await context.bot.send_message(opp_id, "Дуэль завершена.")
        else:
            PVP_QUEUE[user_id] = {"team": team, "tactic": tactic}
            await query.edit_message_text("Ждём второго игрока...")
    else:
        team1 = await _build_team(user_id)
        team2 = await _build_team(0)  # бот
        tactic2 = random.choice(list(TACTICS.values()))
        result = await _run_battle(user_id, "Bot", team1, team2, tactic, tactic2)
        context.user_data["log"] = result["log"]
        context.user_data["log_page"] = 0
        await show_log_page(update, context)

async def show_log_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    page = context.user_data.get("log_page", 0)
    log = context.user_data.get("log", [])
    lines = log[page * 5:(page + 1) * 5]
    text = "\n".join(lines)
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data="log_prev"))
    if (page + 1) * 5 < len(log):
        buttons.append(InlineKeyboardButton("➡️ Далее", callback_data="log_next"))
    reply_markup = InlineKeyboardMarkup([buttons]) if buttons else None
    await update.callback_query.edit_message_text(text or "Нет логов", reply_markup=reply_markup)

async def log_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "log_prev":
        context.user_data["log_page"] = max(0, context.user_data.get("log_page", 0) - 1)
    elif query.data == "log_next":
        context.user_data["log_page"] = context.user_data.get("log_page", 0) + 1
    await show_log_page(update, context)

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
