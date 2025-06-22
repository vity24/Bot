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

TEAM_PAGE = 10


async def create_team(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["team_build"] = {"step": "name"}
    await update.message.reply_text("Введите название команды:")


async def team_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tb = context.user_data.get("team_build")
    if not tb:
        return
    if tb.get("step") == "name":
        tb["name"] = update.message.text.strip()[:30]
        tb["step"] = "select"
        tb["selected"] = []
        tb["page"] = 0
        # explicitly store the updated state back just in case the dict
        # reference is not preserved by the persistence implementation
        context.user_data["team_build"] = tb
        await send_team_page(update.message.chat_id, update.effective_user.id, context)


async def send_team_page(chat_id, user_id, context, edit=False, message_id=None):
    tb = context.user_data.get("team_build", {})
    page = tb.get("page", 0)
    selected = tb.get("selected", [])
    cards = {c["id"]: c for c in get_user_cards(user_id)}
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
        name = cards[cid]["name"]
        mark = " ✅" if cid in selected else ""
        buttons.append([InlineKeyboardButton(name + mark, callback_data=f"team_sel_{cid}")])
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
    if not tb:
        return
    data = query.data
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

async def _build_team(user_id, ids=None):
    cards = get_user_cards(user_id)
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

async def _run_battle(user_id, opponent_name, team1, team2, tactic1, tactic2, name1="Team1", name2="Team2"):
    session = BattleSession(team1, team2, tactic1=tactic1, tactic2=tactic2, name1=name1, name2=name2)
    result = await asyncio.to_thread(session.simulate)
    db.save_battle_result(user_id, opponent_name, result)
    return result

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
        if PVP_QUEUE:
            opp_id, opp_data = PVP_QUEUE.popitem()
            opponent_team = opp_data["team"]
            tactic2 = opp_data["tactic"]
            opp_name = opp_data.get("name", "Team2")
            result = await _run_battle(user_id, str(opp_id), team, opponent_team, tactic, tactic2, team_name, opp_name)
            context.user_data["log"] = result["log"]
            context.user_data["log_page"] = 0
            await show_log_page(update, context)
            await context.bot.send_message(opp_id, "Дуэль завершена.")
        else:
            PVP_QUEUE[user_id] = {"team": team, "tactic": tactic, "name": team_name}
            await query.edit_message_text("Ждём второго игрока...")
    else:
        team1 = team
        team2 = await _build_team(0)
        tactic2 = random.choice(list(TACTICS.values()))
        result = await _run_battle(user_id, "Bot", team1, team2, tactic, tactic2, team_name, "Bot")
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
    else:
        buttons.append(InlineKeyboardButton("❌ Закрыть", callback_data="log_close"))
    reply_markup = InlineKeyboardMarkup([buttons]) if buttons else None
    await update.callback_query.edit_message_text(text or "Нет логов", reply_markup=reply_markup)

async def log_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "log_prev":
        context.user_data["log_page"] = max(0, context.user_data.get("log_page", 0) - 1)
    elif query.data == "log_next":
        context.user_data["log_page"] = context.user_data.get("log_page", 0) + 1
    elif query.data == "log_close":
        context.user_data.pop("log", None)
        context.user_data.pop("log_page", None)
        await query.message.delete()
        return
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
