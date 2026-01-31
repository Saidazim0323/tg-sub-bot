# app/admin.py
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

from .config import ADMIN_IDS
from .database import Session
from .models import Subscription, Payment
from .reports import build_payments_xlsx, payments_stats
from .antispam import allow_click, allow_message

# ✅ pay_code chiqishi uchun Payment+User join qiladigan service
from .services import list_payments_since


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
async def load_last_30_simple():
    """Oxirgi 30 ta to‘lov (pay_code shart emas)"""
    async with Session() as s:
        # select(Payment) ishlatamiz (SQLAlchemy 2.0 style)
        from sqlalchemy import select
        res = await s.execute(select(Payment).order_by(Payment.id.desc()).limit(30))
        return res.scalars().all()


def to_rows_simple(items: list[Payment]):
    """Payment obyektidan dict (pay_code yo‘q)"""
    out = []
    for p in items:
        out.append({
            "id": p.id,
            "created_at": p.created_at,
            "tg_id": p.tg_id,
            "pay_code": None,
            "provider": p.provider,
            "amount": p.amount,
            "status": p.status,
            "plan_days": p.plan_days,
            "ext_id": p.ext_id,
        })
    return out


async def safe_edit_or_send(call: CallbackQuery, text: str, reply_markup=None):
    """edit_text xato bersa ham javob qaytaradi"""
    try:
        await call.message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        await call.message.answer(text, reply_markup=reply_markup)


# =========================
# REGISTER
# =========================
def register_admin(dp):

    # -------------------------
    # /admin
    # -------------------------
    @dp.message(F.text == "/admin")
    async def admin_panel(msg: Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        if not allow_message(msg.from_user.id, delay=1.0):
            return

        await msg.answer(
            "👑 <b>Admin panel</b>\nPastdagi menyudan tanlang 👇",
            reply_markup=admin_reply_kb()
        )

    # -------------------------
    # Buyruqlar
    # -------------------------
    @dp.message(F.text == "ℹ️ Buyruqlar")
    async def admin_help(msg: Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        if not allow_message(msg.from_user.id, delay=0.8):
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

    # -------------------------
    # Obuna berish (hint)
    # -------------------------
    @dp.message(F.text == "🎁 Obuna berish")
    async def admin_give_hint(msg: Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        if not allow_message(msg.from_user.id, delay=0.8):
            return

        await msg.answer(
            "🎁 <b>Obuna berish</b>\n\n"
            "<code>/give USER_ID KUN</code>\n"
            "Misol:\n"
            "<code>/give 123456789 30</code>",
            reply_markup=admin_reply_kb()
        )

    # -------------------------
    # /give USER_ID DAYS
    # -------------------------
    @dp.message(F.text.startswith("/give"))
    async def give(msg: Message):
        if msg.from_user.id not in ADMIN_IDS:
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

        now = datetime.utcnow()

        async with Session() as s:
            sub = await s.get(Subscription, uid)
            if sub and sub.active and sub.expires_at > now:
                sub.expires_at = sub.expires_at + timedelta(days=days)
            else:
                if not sub:
                    sub = Subscription(tg_id=uid, expires_at=now + timedelta(days=days), active=True)
                    s.add(sub)
                else:
                    sub.expires_at = now + timedelta(days=days)
                    sub.active = True
                    sub.warned_3d = False
                    sub.warned_1d = False
                    sub.last_renewal_notice = None

            await s.commit()

        await msg.answer("✅ Obuna berildi", reply_markup=admin_reply_kb())

    # -------------------------
    # To‘lovlar (oxirgi 30)
    # -------------------------
    @dp.message(F.text == "📊 To‘lovlar")
    async def payments(msg: Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        if not allow_message(msg.from_user.id, delay=0.8):
            return

        items = await load_last_30_simple()
        if not items:
            await msg.answer("📊 To‘lovlar yo‘q", reply_markup=admin_reply_kb())
            return

        text = "\n".join(
            f"{p.created_at:%m-%d %H:%M} | {p.tg_id} | {p.provider} | {p.amount} so'm | {p.status}"
            for p in items
        )
        await msg.answer("📊 <b>Oxirgi 30 ta to‘lov</b>\n\n" + text, reply_markup=admin_reply_kb())

    # -------------------------
    # Statistika entry
    # -------------------------
    @dp.message(F.text == "📈 Statistika")
    async def stats_entry(msg: Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        if not allow_message(msg.from_user.id, delay=0.8):
            return

        await msg.answer("📈 <b>Statistika</b>\nTanlang 👇", reply_markup=stats_inline_kb())

    # -------------------------
    # STAT: today
    # -------------------------
    @dp.callback_query(F.data == "stats:today")
    async def stats_today(call: CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            await call.answer("Ruxsat yo‘q", show_alert=True)
            return
        if not allow_click(call.from_user.id, delay=1.5):
            await call.answer("⏳", show_alert=False)
            return

        start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        rows = await list_payments_since(start)  # ✅ pay_code bilan
        st = payments_stats(rows)

        text = (
            "📈 <b>Bugungi statistika (UTC)</b>\n\n"
            f"ALL: {st.get('all', {}).get('count', 0)} ta | {st.get('all', {}).get('sum', 0):,} so'm\n"
            f"PAYME: {st.get('payme', {}).get('count', 0)} ta | {st.get('payme', {}).get('sum', 0):,} so'm\n"
            f"CLICK: {st.get('click', {}).get('count', 0)} ta | {st.get('click', {}).get('sum', 0):,} so'm\n"
        )

        await safe_edit_or_send(call, text, reply_markup=stats_inline_kb())
        await call.answer()

    # -------------------------
    # STAT: 30d
    # -------------------------
    @dp.callback_query(F.data == "stats:30d")
    async def stats_30d(call: CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            await call.answer("Ruxsat yo‘q", show_alert=True)
            return
        if not allow_click(call.from_user.id, delay=1.5):
            await call.answer("⏳", show_alert=False)
            return

        start = datetime.utcnow() - timedelta(days=30)
        rows = await list_payments_since(start)  # ✅ pay_code bilan
        st = payments_stats(rows)

        text = (
            "📈 <b>Oxirgi 30 kun statistika (UTC)</b>\n\n"
            f"ALL: {st.get('all', {}).get('count', 0)} ta | {st.get('all', {}).get('sum', 0):,} so'm\n"
            f"PAYME: {st.get('payme', {}).get('count', 0)} ta | {st.get('payme', {}).get('sum', 0):,} so'm\n"
            f"CLICK: {st.get('click', {}).get('count', 0)} ta | {st.get('click', {}).get('sum', 0):,} so'm\n"
        )

        await safe_edit_or_send(call, text, reply_markup=stats_inline_kb())
        await call.answer()

    # -------------------------
    # XLSX: today
    # -------------------------
    @dp.callback_query(F.data == "xlsx:today")
    async def xlsx_today(call: CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            await call.answer("Ruxsat yo‘q", show_alert=True)
            return
        if not allow_click(call.from_user.id, delay=2.0):
            await call.answer("⏳", show_alert=False)
            return

        start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        rows = await list_payments_since(start)

        data = build_payments_xlsx(rows, "Today")
        fname = f"payments_today_{datetime.utcnow():%Y%m%d_%H%M}.xlsx"

        await call.message.answer_document(
            BufferedInputFile(data, filename=fname),
            caption="📄 Bugungi Excel hisobot"
        )
        await call.answer()

    # -------------------------
    # XLSX: 30d
    # -------------------------
    @dp.callback_query(F.data == "xlsx:30d")
    async def xlsx_30d(call: CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            await call.answer("Ruxsat yo‘q", show_alert=True)
            return
        if not allow_click(call.from_user.id, delay=2.0):
            await call.answer("⏳", show_alert=False)
            return

        start = datetime.utcnow() - timedelta(days=30)
        rows = await list_payments_since(start)

        data = build_payments_xlsx(rows, "Last 30 days")
        fname = f"payments_30d_{datetime.utcnow():%Y%m%d_%H%M}.xlsx"

        await call.message.answer_document(
            BufferedInputFile(data, filename=fname),
            caption="📄 Oxirgi 30 kun Excel hisobot"
        )
        await call.answer()

    # -------------------------
    # Back
    # -------------------------
    @dp.callback_query(F.data == "stats:back")
    async def stats_back(call: CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            await call.answer("Ruxsat yo‘q", show_alert=True)
            return
        if not allow_click(call.from_user.id, delay=1.0):
            await call.answer("⏳", show_alert=False)
            return

        await safe_edit_or_send(call, "📈 <b>Statistika</b>\nTanlang 👇", reply_markup=stats_inline_kb())
        await call.answer()
