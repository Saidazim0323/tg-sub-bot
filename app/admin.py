from datetime import datetime, timedelta

from aiogram import F
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)

from sqlalchemy import select

from .config import ADMIN_ID
from .database import Session
from .models import Subscription, Payment


def register_admin(dp):
    # ✅ Admin panel (tugmalar)
    @dp.message(F.text == "/admin")
    async def admin_menu(msg: Message):
        if msg.from_user.id != ADMIN_ID:
            return

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Obuna berish", callback_data="admin:give")],
            [InlineKeyboardButton(text="📊 To‘lovlar", callback_data="admin:payments")],
            [InlineKeyboardButton(text="ℹ️ Buyruqlar", callback_data="admin:help")],
        ])
        await msg.answer("👑 <b>Admin panel</b>", reply_markup=kb)

    # ✅ Admin help
    @dp.callback_query(F.data == "admin:help")
    async def admin_help(call: CallbackQuery):
        if call.from_user.id != ADMIN_ID:
            await call.answer("Ruxsat yo‘q", show_alert=True)
            return

        await call.message.answer(
            "👑 <b>Admin buyruqlari</b>\n\n"
            "/admin — admin panel\n"
            "/give USER_ID KUN — obuna berish\n"
            "/payments — to‘lovlar (oxirgi 30 ta)\n"
            "Tugma: 📊 To‘lovlar — to‘lovlar ro‘yxati"
        )
        await call.answer()

    # ✅ Tugma: obuna berish yo‘riqnoma
    @dp.callback_query(F.data == "admin:give")
    async def admin_give_hint(call: CallbackQuery):
        if call.from_user.id != ADMIN_ID:
            await call.answer("Ruxsat yo‘q", show_alert=True)
            return

        await call.message.answer(
            "🎁 <b>Obuna berish</b>\n\n"
            "Format:\n"
            "<code>/give USER_ID KUN</code>\n\n"
            "Misol:\n"
            "<code>/give 123456789 30</code>"
        )
        await call.answer()

    # ✅ Tugma: To‘lovlar (callback) — ISHLAYDI
    @dp.callback_query(F.data == "admin:payments")
    async def admin_payments(call: CallbackQuery):
        if call.from_user.id != ADMIN_ID:
            await call.answer("Ruxsat yo‘q", show_alert=True)
            return

        async with Session() as s:
            res = await s.execute(select(Payment).order_by(Payment.id.desc()).limit(30))
            items = res.scalars().all()

        if not items:
            await call.message.answer("📊 To‘lovlar yo‘q")
            await call.answer()
            return

        lines = []
        for p in items:
            lines.append(
                f"{p.created_at:%m-%d %H:%M} | {p.tg_id} | {p.provider} | "
                f"{p.amount} so'm | {p.status} | {p.plan_days} kun"
            )

        await call.message.answer("📊 <b>Oxirgi 30 ta to‘lov</b>\n\n" + "\n".join(lines))
        await call.answer()

    # ✅ Komanda: /give USER_ID DAYS
    @dp.message(F.text.startswith("/give"))
    async def give(msg: Message):
        if msg.from_user.id != ADMIN_ID:
            return

        parts = msg.text.split()
        if len(parts) != 3:
            await msg.answer("Format: /give USER_ID KUN\nMisol: /give 123456789 30")
            return

        _, uid, days = parts
        try:
            uid = int(uid)
            days = int(days)
        except ValueError:
            await msg.answer("Xato: USER_ID va KUN raqam bo‘lishi kerak.")
            return

        async with Session() as s:
            s.add(Subscription(
                tg_id=uid,
                expires_at=datetime.utcnow() + timedelta(days=days),
                active=True
            ))
            await s.commit()

        await msg.answer("✅ Obuna berildi")

    # ✅ Komanda: /payments (oxirgi 30 ta) — ISHLAYDI
    @dp.message(F.text == "/payments")
    async def payments_cmd(msg: Message):
        if msg.from_user.id != ADMIN_ID:
            return

        async with Session() as s:
            res = await s.execute(select(Payment).order_by(Payment.id.desc()).limit(30))
            items = res.scalars().all()

        if not items:
            await msg.answer("To‘lovlar yo‘q")
            return

        text = "\n".join(
            f"{p.created_at:%m-%d %H:%M} | {p.tg_id} | {p.provider} | {p.amount} | {p.status} | {p.plan_days} kun"
            for p in items
        )
        await msg.answer(text)
