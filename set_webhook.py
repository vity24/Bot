import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
URL = f"https://Vitaly24.pythonanywhere.com/webhook/{TOKEN}"

res = requests.get(f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={URL}")
print(res.text)
