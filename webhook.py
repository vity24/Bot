import os
from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import Application
from dotenv import load_dotenv

# Загрузка переменных
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(TOKEN)
application = Application.builder().token(TOKEN).build()

app = Flask(__name__)

@app.post(f"/webhook/{TOKEN}")
async def webhook():
    update_data = request.get_json(force=True)
    update = Update.de_json(update_data, bot)
    await application.process_update(update)
    return "ok"
