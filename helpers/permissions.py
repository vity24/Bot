ADMINS = [445479731, 6463889816]  # указать реальные ID


def is_admin(user_id: int) -> bool:
    return user_id in ADMINS

from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes


def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not is_admin(user.id):
            await update.message.reply_text("⛔️ Команда доступна только администраторам.")
            return
        return await func(update, context, *args, **kwargs)

    return wrapper
