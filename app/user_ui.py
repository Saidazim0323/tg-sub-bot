# app/user_ui.py
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def user_reply_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💳 To‘lov qilish"), KeyboardButton(text="👤 Obunam")],
            [KeyboardButton(text="🔄 Yangilash"), KeyboardButton(text="ℹ️ Yordam")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )
