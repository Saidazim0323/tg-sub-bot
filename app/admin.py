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
from .services import ensure_user, list_payments_since

from .services import deactivate_subscription
from .config import GROUP_ID, CHANNEL_ID

# =========================
# Pastki ADMIN MENU (doim turadi)
# =========================
def admin_reply_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎁 Obuna berish"), KeyboardButton(text="📊 To‘lovlar")],
            [KeyboardButton(text="📈 Statistika"), KeyboardButton(text="ℹ️ Buyruqlar")],
            [KeyboardButton(text="👑 Mening PAY CODE")],
            [KeyboardButton(text="❌ Obunani bekor qilish")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


# =========================
# Statistika INLINE menu
# =========================
def stats_inline_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📈 Bugun", callback_data="stats:today")],
            [InlineKeyboardButton(text="📈 30 kun", callback_data="stats:30d")],
            [InlineKeyboardButton(text="📄 Excel (Bugun)", callback_data="xlsx:today")],
            [InlineKeyboardButton(text="📄 Excel (30 kun)", callback_data="xlsx:30d")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="stats:back")],
        ]
    )


async def safe_edit_or_send(call: CallbackQuery, text: str, reply_markup=None):
    try:
        await call.message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        await call.message.answer(text, reply_markup=reply_markup)


async def load_last_30_simple():
    """Oxirgi 30 ta to‘lov (oddiy ro‘yxat)"""
    from sqlalchemy import select
    async with Session() as s:
        res = await s.execute(select(Payment).order_by(Payment.id.desc()).limit(30))
        return res.scalars().all()


# =========================
# REGISTER
# =========================
def register_admin(dp):

    # /admin
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

    # 👑 Mening PAY CODE (ADMIN)
    @dp.message(F.text == "👑 Mening PAY CODE")
    async def admin_my_paycode(msg: Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        if not allow_message(msg.from_user.id, delay=0.8):
            return

        u = await ensure_user(msg.from_user.id)
        await msg.answer(
            "👑 <b>Admin PAY CODE</b>\n\n"
            f"🔐 Sizning PAY CODE: <code>{u.pay_code}</code>",
            reply_markup=admin_reply_kb()
        )

    # Buyruqlar
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
            "📈 Statistika\n"
            "👑 Mening PAY CODE",
            reply_markup=admin_reply_kb()
        )

    # Obuna berish hint
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
        # Bekor qilish hint (tugma bosilganda)
    @dp.message(F.text == "❌ Obunani bekor qilish")
    async def cancel_hint(msg: Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        if not allow_message(msg.from_user.id, delay=0.8):
            return

        await msg.answer(
            "❌ <b>Obunani bekor qilish</b>\n\n"
            "<code>/cancel TG_ID</code>\n"
            "Misol:\n"
            "<code>/cancel 123456789</code>\n\n"
            "Bekor bo‘lgach user guruh va kanaldan chiqariladi.",
            reply_markup=admin_reply_kb()
        )

          # /cancel TG_ID
    @dp.message(F.text.startswith("/cancel"))
    async def cancel_sub(msg: Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        if not allow_message(msg.from_user.id, delay=1.0):
            return

        parts = msg.text.split()
        if len(parts) != 2:
            await msg.answer("Format: /cancel TG_ID", reply_markup=admin_reply_kb())
            return

        try:
            tg_id = int(parts[1])
        except ValueError:
            await msg.answer("Xato: TG_ID raqam bo‘lishi kerak.", reply_markup=admin_reply_kb())
            return

        # 1) DB: obunani bekor qilish
        await deactivate_subscription(tg_id)

        # 2) Guruh + kanaldan chiqarish (kick)
        kicked = []
        for chat_id, name in [(GROUP_ID, "guruh"), (CHANNEL_ID, "kanal")]:
            if not chat_id:
                continue
            try:
                await bot.ban_chat_member(chat_id, tg_id)
                await bot.unban_chat_member(chat_id, tg_id)
                kicked.append(name)
            except Exception:
                # user u yerda bo‘lmasligi mumkin yoki botda huquq yetishmasligi mumkin
                pass

        # 3) Userga xabar (private bo‘lsa)
        try:
            await bot.send_message(
                tg_id,
                "❌ Obunangiz bekor qilindi.\n"
                "Guruh/kanalga kirish yopildi.\n\n"
                "Qayta obuna bo‘lish uchun /start bosing."
            )
        except Exception:
            pass

        kicked_txt = ", ".join(kicked) if kicked else "chiqarilmadi (user yo‘q yoki bot huquqi yetmadi)"
        await msg.answer(
            f"✅ Bekor qilindi: <code>{tg_id}</code>\n"
            f"🚪 Chiqarildi: {kicked_txt}",
            reply_markup=admin_reply_kb()
            )

    # /give USER_ID DAYS
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

    # To‘lovlar (oxirgi 30)
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

    # Statistika entry
    @dp.message(F.text == "📈 Statistika")
    async def stats_entry(msg: Message):
        if msg.from_user.id not in ADMIN_IDS:
            return
        if not allow_message(msg.from_user.id, delay=0.8):
            return
        await msg.answer("📈 <b>Statistika</b>\nTanlang 👇", reply_markup=stats_inline_kb())

    # STAT: today
    @dp.callback_query(F.data == "stats:today")
    async def stats_today(call: CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            await call.answer("Ruxsat yo‘q", show_alert=True)
            return
        if not allow_click(call.from_user.id, delay=1.5):
            await call.answer("⏳", show_alert=False)
            return

        start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        rows = await list_payments_since(start)
        st = payments_stats(rows)

        text = (
            "📈 <b>Bugungi statistika (UTC)</b>\n\n"
            f"ALL: {st.get('all', {}).get('count', 0)} ta | {st.get('all', {}).get('sum', 0):,} so'm\n"
            f"PAYME: {st.get('payme', {}).get('count', 0)} ta | {st.get('payme', {}).get('sum', 0):,} so'm\n"
            f"CLICK: {st.get('click', {}).get('count', 0)} ta | {st.get('click', {}).get('sum', 0):,} so'm\n"
        )
        await safe_edit_or_send(call, text, reply_markup=stats_inline_kb())
        await call.answer()

    # STAT: 30d
    @dp.callback_query(F.data == "stats:30d")
    async def stats_30d(call: CallbackQuery):
        if call.from_user.id not in ADMIN_IDS:
            await call.answer("Ruxsat yo‘q", show_alert=True)
            return
        if not allow_click(call.from_user.id, delay=1.5):
            await call.answer("⏳", show_alert=False)
            return

        start = datetime.utcnow() - timedelta(days=30)
        rows = await list_payments_since(start)
        st = payments_stats(rows)

        text = (
            "📈 <b>Oxirgi 30 kun statistika (UTC)</b>\n\n"
            f"ALL: {st.get('all', {}).get('count', 0)} ta | {st.get('all', {}).get('sum', 0):,} so'm\n"
            f"PAYME: {st.get('payme', {}).get('count', 0)} ta | {st.get('payme', {}).get('sum', 0):,} so'm\n"
            f"CLICK: {st.get('click', {}).get('count', 0)} ta | {st.get('click', {}).get('sum', 0):,} so'm\n"
        )
        await safe_edit_or_send(call, text, reply_markup=stats_inline_kb())
        await call.answer()

    # XLSX: today
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

    # XLSX: 30d
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

    # Back
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
