from datetime import datetime, timedelta

from aiogram import F
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.types.input_file import BufferedInputFile
from sqlalchemy import select

from .config import ADMIN_IDS
from .database import Session
from .models import Subscription, Payment
from .reports import build_payments_xlsx, payments_stats
from .antispam import allow_click, allow_message


# =========================
# Pastki ADMIN MENU (doim turadi)
# =========================
def admin_reply_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎁 Obuna berish"), KeyboardButton(text="📊 To‘lovlar")],
            [KeyboardButton(text="📈 Statistika"), KeyboardButton(text="ℹ️ Buyruqlar")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


# =========================
# Statistika INLINE menu
# =========================
def stats_inline_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 Bugun", callback_data="stats:today")],
        [InlineKeyboardButton(text="📈 30 kun", callback_data="stats:30d")],
        [InlineKeyboardButton(text="📄 Excel (Bugun)", callback_data="xlsx:today")],
        [InlineKeyboardButton(text="📄 Excel (30 kun)", callback_data="xlsx:30d")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="stats:back")],
    ])


# =========================
# DB helpers
# =========================
async def load_payments_since(dt: datetime):
    async with Session() as s:
        res = await s.execute(
            select(Payment)
            .where(Payment.created_at >= dt)
            .order_by(Payment.created_at.desc())
        )
        return res.scalars().all()


async def load_last_30():
    async with Session() as s:
        res = await s.execute(
            select(Payment).order_by(Payment.id.desc()).limit(30)
        )
        return res.scalars().all()


def to_rows(items: list[Payment]):
    return [{
        "id": p.id,
        "created_at": p.created_at,
        "tg_id": p.tg_id,
        "provider": p.provider,
        "amount": p.amount,
        "status": p.status,
        "plan_days": p.plan_days,
        "ext_id": p.ext_id,
    } for p in items]


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# =========================
# REGISTER
# =========================
def register_admin(dp):

    # =========================
    # /admin (panelni chiqaradi)
    # =========================
    @dp.message(F.text == "/admin")
    async def admin_panel(msg: Message):
        if not _is_admin(msg.from_user.id):
            return
        if not allow_message(msg.from_user.id, delay=1.0):
            return

        await msg.answer(
            "👑 <b>Admin panel</b>\nPastdagi menyudan tanlang 👇",
            reply_markup=admin_reply_kb()
        )

    # =========================
    # BUYRUQLAR
    # =========================
    @dp.message(F.text == "ℹ️ Buyruqlar")
    async def admin_help(msg: Message):
        if not _is_admin(msg.from_user.id):
            return
        if not allow_message(msg.from_user.id, delay=1.0):
            return

        await msg.answer(
            "👑 <b>Admin buyruqlari</b>\n\n"
            "/admin — admin panel\n"
            "/give USER_ID KUN — obuna berish\n\n"
            "Pastki menyu:\n"
            "🎁 Obuna berish\n"
            "📊 To‘lovlar\n"
            "📈 Statistika",
            reply_markup=admin_reply_kb()
        )

    # =========================
    # OBUNA BERISH (yo‘riqnoma)
    # =========================
    @dp.message(F.text == "🎁 Obuna berish")
    async def admin_give_hint(msg: Message):
        if not _is_admin(msg.from_user.id):
            return
        if not allow_message(msg.from_user.id, delay=1.0):
            return

        await msg.answer(
            "🎁 <b>Obuna berish</b>\n\n"
            "<code>/give USER_ID KUN</code>\n"
            "Misol:\n"
            "<code>/give 123456789 30</code>",
            reply_markup=admin_reply_kb()
        )

    # =========================
    # /give USER_ID DAYS
    # =========================
    @dp.message(F.text.startswith("/give"))
    async def give(msg: Message):
        if not _is_admin(msg.from_user.id):
            return
        if not allow_message(msg.from_user.id, delay=1.0):
            return

        parts = msg.text.split()
        if len(parts) != 3:
            await msg.answer("Format: /give USER_ID KUN", reply_markup=admin_reply_kb())
            return

        _, uid, days = parts
        try:
            uid, days = int(uid), int(days)
        except ValueError:
            await msg.answer("Xato: USER_ID va KUN raqam bo‘lishi kerak.", reply_markup=admin_reply_kb())
            return

        async with Session() as s:
            sub = await s.get(Subscription, uid)
            now = datetime.utcnow()
            exp = now + timedelta(days=days)

            if sub:
                sub.expires_at = exp
                sub.active = True
                sub.warned_3d = False
                sub.warned_1d = False
            else:
                s.add(Subscription(
                    tg_id=uid,
                    expires_at=exp,
                    active=True
                ))
            await s.commit()

        await msg.answer(f"✅ Obuna berildi: {uid} ({days} kun)", reply_markup=admin_reply_kb())

    # =========================
    # TO‘LOVLAR (oxirgi 30 ta)
    # =========================
    @dp.message(F.text == "📊 To‘lovlar")
    async def payments(msg: Message):
        if not _is_admin(msg.from_user.id):
            return
        if not allow_message(msg.from_user.id, delay=1.0):
            return

        items = await load_last_30()
        if not items:
            await msg.answer("📊 To‘lovlar yo‘q", reply_markup=admin_reply_kb())
            return

        text = "\n".join(
            f"{p.created_at:%m-%d %H:%M} | {p.tg_id} | {p.provider} | {p.amount} so'm | {p.status}"
            for p in items
        )
        await msg.answer(
            "📊 <b>Oxirgi 30 ta to‘lov</b>\n\n" + text,
            reply_markup=admin_reply_kb()
        )

    # =========================
    # STATISTIKA (entry)
    # =========================
    @dp.message(F.text == "📈 Statistika")
    async def stats_entry(msg: Message):
        if not _is_admin(msg.from_user.id):
            return
        if not allow_message(msg.from_user.id, delay=1.0):
            return

        await msg.answer(
            "📈 <b>Statistika</b>\nTanlang 👇",
            reply_markup=stats_inline_kb()
        )

    # =========================
    # CALLBACKS: STATISTIKA BUGUN
    # =========================
    @dp.callback_query(F.data == "stats:today")
    async def stats_today(call: CallbackQuery):
        if not _is_admin(call.from_user.id):
            await call.answer("Ruxsat yo‘q", show_alert=True)
            return
        if not allow_click(call.from_user.id, delay=1.2):
            await call.answer("⏳", show_alert=False)
            return

        start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        items = await load_payments_since(start)
        st = payments_stats(to_rows(items))

        text = (
            "📈 <b>Bugungi statistika (UTC)</b>\n\n"
            f"ALL: {st['all']['count']} ta | {st['all']['sum']:,} so'm\n"
            f"PAYME: {st['payme']['count']} ta | {st['payme']['sum']:,} so'm\n"
            f"CLICK: {st['click']['count']} ta | {st['click']['sum']:,} so'm"
        )
        await call.message.edit_text(text, reply_markup=stats_inline_kb())
        await call.answer()

    # =========================
    # CALLBACKS: STATISTIKA 30 KUN
    # =========================
    @dp.callback_query(F.data == "stats:30d")
    async def stats_30d(call: CallbackQuery):
        if not _is_admin(call.from_user.id):
            await call.answer("Ruxsat yo‘q", show_alert=True)
            return
        if not allow_click(call.from_user.id, delay=1.2):
            await call.answer("⏳", show_alert=False)
            return

        start = datetime.utcnow() - timedelta(days=30)
        items = await load_payments_since(start)
        st = payments_stats(to_rows(items))

        text = (
            "📈 <b>Oxirgi 30 kun statistika (UTC)</b>\n\n"
            f"ALL: {st['all']['count']} ta | {st['all']['sum']:,} so'm\n"
            f"PAYME: {st['payme']['count']} ta | {st['payme']['sum']:,} so'm\n"
            f"CLICK: {st['click']['count']} ta | {st['click']['sum']:,} so'm"
        )
        await call.message.edit_text(text, reply_markup=stats_inline_kb())
        await call.answer()

    # =========================
    # EXCEL (BUGUN)
    # =========================
    @dp.callback_query(F.data == "xlsx:today")
    async def xlsx_today(call: CallbackQuery):
        if not _is_admin(call.from_user.id):
            await call.answer("Ruxsat yo‘q", show_alert=True)
            return
        if not allow_click(call.from_user.id, delay=2.0):
            await call.answer("⏳", show_alert=False)
            return

        start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        items = await load_payments_since(start)

        data = build_payments_xlsx(to_rows(items), "Today")
        fname = f"payments_today_{datetime.utcnow():%Y%m%d_%H%M}.xlsx"

        await call.message.answer_document(
            BufferedInputFile(data, filename=fname),
            caption="📄 Bugungi Excel hisobot"
        )
        await call.answer()

    # =========================
    # EXCEL (30 KUN)
    # =========================
    @dp.callback_query(F.data == "xlsx:30d")
    async def xlsx_30d(call: CallbackQuery):
        if not _is_admin(call.from_user.id):
            await call.answer("Ruxsat yo‘q", show_alert=True)
            return
        if not allow_click(call.from_user.id, delay=2.0):
            await call.answer("⏳", show_alert=False)
            return

        start = datetime.utcnow() - timedelta(days=30)
        items = await load_payments_since(start)

        data = build_payments_xlsx(to_rows(items), "Last 30 days")
        fname = f"payments_30d_{datetime.utcnow():%Y%m%d_%H%M}.xlsx"

        await call.message.answer_document(
            BufferedInputFile(data, filename=fname),
            caption="📄 Oxirgi 30 kun Excel hisobot"
        )
        await call.answer()

    # =========================
    # BACK (statistika menyusiga qaytadi)
    # =========================
    @dp.callback_query(F.data == "stats:back")
    async def stats_back(call: CallbackQuery):
        if not _is_admin(call.from_user.id):
            await call.answer("Ruxsat yo‘q", show_alert=True)
            return
        if not allow_click(call.from_user.id, delay=1.0):
            await call.answer("⏳", show_alert=False)
            return

        await call.message.edit_text(
            "📈 <b>Statistika</b>\nTanlang 👇",
            reply_markup=stats_inline_kb()
        )
        await call.answer()
