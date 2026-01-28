from datetime import datetime, timedelta

from aiogram import F
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)
from aiogram.types.input_file import BufferedInputFile

from sqlalchemy import select

from .config import ADMIN_ID
from .database import Session
from .models import Subscription, Payment
from .reports import build_payments_xlsx, payments_stats


def _to_rows(items: list[Payment]) -> list[dict]:
    out = []
    for p in items:
        out.append({
            "id": p.id,
            "created_at": p.created_at,
            "tg_id": p.tg_id,
            "provider": p.provider,
            "amount": p.amount,
            "status": p.status,
            "plan_days": getattr(p, "plan_days", 30),
            "ext_id": getattr(p, "ext_id", None),
        })
    return out


async def _load_payments_last_30():
    async with Session() as s:
        res = await s.execute(select(Payment).order_by(Payment.id.desc()).limit(30))
        return res.scalars().all()


async def _load_payments_since(dt_utc: datetime):
    async with Session() as s:
        res = await s.execute(
            select(Payment)
            .where(Payment.created_at >= dt_utc)
            .order_by(Payment.id.desc())
        )
        return res.scalars().all()


def register_admin(dp):
    # ✅ Admin panel (tugmalar)
    @dp.message(F.text == "/admin")
    async def admin_menu(msg: Message):
        if msg.from_user.id != ADMIN_ID:
            return

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Obuna berish", callback_data="admin:give")],
            [InlineKeyboardButton(text="📊 To‘lovlar (30 ta)", callback_data="admin:payments")],
            [InlineKeyboardButton(text="📈 Statistika (Bugun)", callback_data="admin:stats_today")],
            [InlineKeyboardButton(text="📈 Statistika (30 kun)", callback_data="admin:stats_30d")],
            [InlineKeyboardButton(text="📄 Excel (Bugun)", callback_data="admin:xlsx_today")],
            [InlineKeyboardButton(text="📄 Excel (30 kun)", callback_data="admin:xlsx_30d")],
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
            "/payments — oxirgi 30 ta to‘lov\n\n"
            "Panel tugmalari:\n"
            "📊 To‘lovlar (30 ta)\n"
            "📈 Statistika (Bugun / 30 kun)\n"
            "📄 Excel (Bugun / 30 kun)\n"
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

    # ✅ Tugma: To‘lovlar (callback) — oxirgi 30 ta
    @dp.callback_query(F.data == "admin:payments")
    async def admin_payments(call: CallbackQuery):
        if call.from_user.id != ADMIN_ID:
            await call.answer("Ruxsat yo‘q", show_alert=True)
            return

        items = await _load_payments_last_30()

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

    # ✅ Statistika: bugun (UTC)
    @dp.callback_query(F.data == "admin:stats_today")
    async def stats_today(call: CallbackQuery):
        if call.from_user.id != ADMIN_ID:
            await call.answer("Ruxsat yo‘q", show_alert=True)
            return

        now = datetime.utcnow()
        start = datetime(now.year, now.month, now.day)  # UTC today 00:00
        items = await _load_payments_since(start)

        rows = _to_rows(items)
        st = payments_stats(rows)

        def g(name):
            x = st.get(name, {"count": 0, "sum": 0})
            return x["count"], x["sum"]

        all_c, all_s = g("all")
        payme_c, payme_s = g("payme")
        click_c, click_s = g("click")

        await call.message.answer(
            "📈 <b>Statistika (Bugun, UTC)</b>\n\n"
            f"ALL: {all_c} ta | {all_s:,} so'm\n"
            f"PAYME: {payme_c} ta | {payme_s:,} so'm\n"
            f"CLICK: {click_c} ta | {click_s:,} so'm\n"
        )
        await call.answer()

    # ✅ Statistika: 30 kun (UTC)
    @dp.callback_query(F.data == "admin:stats_30d")
    async def stats_30d(call: CallbackQuery):
        if call.from_user.id != ADMIN_ID:
            await call.answer("Ruxsat yo‘q", show_alert=True)
            return

        start = datetime.utcnow() - timedelta(days=30)
        items = await _load_payments_since(start)

        rows = _to_rows(items)
        st = payments_stats(rows)

        def g(name):
            x = st.get(name, {"count": 0, "sum": 0})
            return x["count"], x["sum"]

        all_c, all_s = g("all")
        payme_c, payme_s = g("payme")
        click_c, click_s = g("click")

        await call.message.answer(
            "📈 <b>Statistika (Oxirgi 30 kun, UTC)</b>\n\n"
            f"ALL: {all_c} ta | {all_s:,} so'm\n"
            f"PAYME: {payme_c} ta | {payme_s:,} so'm\n"
            f"CLICK: {click_c} ta | {click_s:,} so'm\n"
        )
        await call.answer()

    # ✅ Excel: bugun (UTC)
    @dp.callback_query(F.data == "admin:xlsx_today")
    async def xlsx_today(call: CallbackQuery):
        if call.from_user.id != ADMIN_ID:
            await call.answer("Ruxsat yo‘q", show_alert=True)
            return

        now = datetime.utcnow()
        start = datetime(now.year, now.month, now.day)
        items = await _load_payments_since(start)

        rows = _to_rows(items)
        xlsx = build_payments_xlsx(rows, "Payments - Today (UTC)")
        filename = f"payments_today_utc_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"

        await call.message.answer_document(
            BufferedInputFile(xlsx, filename=filename),
            caption="📄 Excel hisobot (Bugun, UTC)"
        )
        await call.answer()

    # ✅ Excel: 30 kun (UTC)
    @dp.callback_query(F.data == "admin:xlsx_30d")
    async def xlsx_30d(call: CallbackQuery):
        if call.from_user.id != ADMIN_ID:
            await call.answer("Ruxsat yo‘q", show_alert=True)
            return

        start = datetime.utcnow() - timedelta(days=30)
        items = await _load_payments_since(start)

        rows = _to_rows(items)
        xlsx = build_payments_xlsx(rows, "Payments - Last 30 days (UTC)")
        filename = f"payments_30d_utc_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"

        await call.message.answer_document(
            BufferedInputFile(xlsx, filename=filename),
            caption="📄 Excel hisobot (Oxirgi 30 kun, UTC)"
        )
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

    # ✅ Komanda: /payments (oxirgi 30 ta)
    @dp.message(F.text == "/payments")
    async def payments_cmd(msg: Message):
        if msg.from_user.id != ADMIN_ID:
            return

        items = await _load_payments_last_30()
        if not items:
            await msg.answer("To‘lovlar yo‘q")
            return

        text = "\n".join(
            f"{p.created_at:%m-%d %H:%M} | {p.tg_id} | {p.provider} | {p.amount} | {p.status} | {p.plan_days} kun"
            for p in items
        )
        await msg.answer(text)
