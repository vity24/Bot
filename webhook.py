import os
from dotenv import load_dotenv
from quart import Quart, request
from telegram import Update
from telegram.ext import Application

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")

application = Application.builder().token(TOKEN).build()

app = Quart(__name__)

@app.post(f"/webhook/{TOKEN}")
async def telegram_webhook():
    update = Update.de_json(await request.get_json(force=True), application.bot)
    await application.process_update(update)
    return "ok"
