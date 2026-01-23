import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
from .config import BOT_TOKEN, GROUP_ID, CHANNEL_ID
from .database import engine, Session
from .models import Base, Subscription
from .admin import register_admin

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

@dp.message(F.text == "/start")
async def start(msg: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="30 kun – 50 000 so'm", callback_data="buy")]
    ])
    await msg.answer("Obuna tanlang 👇", reply_markup=kb)

@dp.callback_query(F.data == "buy")
async def buy(call):
    await call.message.answer("💳 Click yoki Payme orqali to‘lov qiling")

async def check_subs():
    async with Session() as s:
        rows = await s.execute(Subscription.__table__.select())
        for sub in rows.fetchall():
            if sub.active and sub.expires_at < datetime.utcnow():
                await bot.ban_chat_member(GROUP_ID, sub.tg_id)
                await bot.ban_chat_member(CHANNEL_ID, sub.tg_id)
                sub.active = False
        await s.commit()

async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    register_admin(dp)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_subs, "interval", hours=6)
    scheduler.start()

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
