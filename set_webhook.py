import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("WEBHOOK_BASE", "Vitaly24.pythonanywhere.com")

url = f"https://{BASE_URL}/webhook/{TOKEN}"
res = requests.get(f"https://api.telegram.org/bot{TOKEN}/setWebhook", params={"url": url})
print(res.text)
