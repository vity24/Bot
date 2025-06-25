import requests

TOKEN = "7649956181:AAErINkWzZJ7BofoorAHxc2fLXMPoaCjkQM"
URL = f"https://Vitaly24.pythonanywhere.com/webhook/{TOKEN}"

res = requests.get(f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={URL}")
print(res.text)
