import asyncio
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ChatMemberUpdated,
)
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import (
    BOT_TOKEN, GROUP_ID, CHANNEL_ID,
    PLAN_PRICES_UZS, PAYME_PAY_URL, CLICK_PAY_URL,
    ADMIN_IDS,
)
from .database import Session
from .admin import register_admin, admin_reply_kb
from .services import (
    ensure_user,
    deactivate_subscription,
    get_active_subscriptions,
    expected_amount_uzs,
    normalize_plan_days,
)
from .models import Subscription
from .antispam import allow_click, allow_message
from .user_ui import user_reply_kb


# ================= BOT / DISPATCHER =================
bot = Bot(BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()


# ================= UI =================
def pay_buttons(pay_code: str, amount: int):
    rows = []
    if PAYME_PAY_URL:
        rows.append([InlineKeyboardButton(text="💳 Payme orqali to‘lash", url=PAYME_PAY_URL)])
    if CLICK_PAY_URL:
        rows.append([InlineKeyboardButton(text="💳 Click orqali to‘lash", url=CLICK_PAY_URL)])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def plans_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"7 kun — {PLAN_PRICES_UZS[7]} so'm", callback_data="plan:7")],
        [InlineKeyboardButton(text=f"30 kun — {PLAN_PRICES_UZS[30]} so'm", callback_data="plan:30")],
        [InlineKeyboardButton(text=f"90 kun — {PLAN_PRICES_UZS[90]} so'm", callback_data="plan:90")],
    ])


# ================= /START =================
@dp.message(Command("start"))
async def start_cmd(msg: Message):
    user_id = msg.from_user.id

    if not allow_message(user_id, delay=1.0):
        return

    # 👑 ADMIN
    if user_id in ADMIN_IDS:
        await msg.answer(
            "👑 <b>Admin panel</b>\n\nPastdagi menyudan foydalaning 👇",
            reply_markup=admin_reply_kb()
        )
        return

    # 👤 USER
    u = await ensure_user(user_id)
    await msg.answer(
        "💎 <b>Pullik obuna</b>\n\n"
        f"🔐 PAY CODE: <code>{u.pay_code}</code>\n\n"
        "Pastdagi menyudan foydalaning 👇",
        reply_markup=user_reply_kb()
    )
    await msg.answer("Tarifni tanlang 👇", reply_markup=plans_keyboard())


# ================= USER MENU =================
@dp.message(F.text == "💳 To‘lov qilish")
async def menu_pay(msg: Message):
    if msg.from_user.id in ADMIN_IDS:
        return
    if not allow_message(msg.from_user.id, delay=1.5):
        return

    u = await ensure_user(msg.from_user.id)
    await msg.answer(
        "💳 Tarifni tanlang 👇\n\n"
        f"🔐 PAY CODE: <code>{u.pay_code}</code>",
        reply_markup=plans_keyboard()
    )


@dp.message(F.text == "👤 Obunam")
async def menu_my_sub(msg: Message):
    if msg.from_user.id in ADMIN_IDS:
        return
    if not allow_message(msg.from_user.id, delay=1.5):
        return

    async with Session() as s:
        sub = await s.get(Subscription, msg.from_user.id)

    if not sub or not sub.active or sub.expires_at <= datetime.utcnow():
        await msg.answer("❌ Sizda faol obuna yo‘q.", reply_markup=user_reply_kb())
        return

    left = sub.expires_at - datetime.utcnow()
    days = max(int(left.total_seconds() // 86400), 0)
    hours = max(int((left.total_seconds() % 86400) // 3600), 0)

    await msg.answer(
        "✅ <b>Obuna faol</b>\n\n"
        f"🗓 Tugash vaqti: {sub.expires_at:%Y-%m-%d %H:%M} UTC\n"
        f"⏳ Qoldi: {days} kun {hours} soat",
        reply_markup=user_reply_kb()
    )


@dp.message(F.text == "🔄 Yangilash")
async def menu_renew(msg: Message):
    if msg.from_user.id in ADMIN_IDS:
        return
    if not allow_message(msg.from_user.id, delay=1.5):
        return

    u = await ensure_user(msg.from_user.id)
    await msg.answer(
        "🔄 Yangilash uchun tarif tanlang 👇\n\n"
        f"🔐 PAY CODE: <code>{u.pay_code}</code>",
        reply_markup=plans_keyboard()
    )


@dp.message(F.text == "ℹ️ Yordam")
async def menu_help(msg: Message):
    if msg.from_user.id in ADMIN_IDS:
        return
    if not allow_message(msg.from_user.id, delay=1.5):
        return

    u = await ensure_user(msg.from_user.id)
    await msg.answer(
        "ℹ️ <b>Yordam</b>\n\n"
        "1) /start bosing\n"
        "2) Tarif tanlang\n"
        "3) Payme/Click’da ID maydoniga PAY CODE yozing\n"
        "4) To‘lov tasdiqlansa link keladi\n\n"
        f"🔐 PAY CODE: <code>{u.pay_code}</code>",
        reply_markup=user_reply_kb()
    )


# ================= PLAN TANLASH =================
@dp.callback_query(F.data.startswith("plan:"))
async def choose_plan(call):
    if call.from_user.id in ADMIN_IDS:
        return
    if not allow_click(call.from_user.id, delay=2.0):
        await call.answer("⏳ Sekinroq 🙂", show_alert=True)
        return

    u = await ensure_user(call.from_user.id)
    days = normalize_plan_days(int(call.data.split(":")[1]))
    price = expected_amount_uzs(days)

    await call.message.answer(
        f"✅ Tarif: {days} kun\n"
        f"💰 Narx: {price} so'm\n\n"
        "ID maydoniga PAY CODE yozing:\n"
        f"<code>{u.pay_code}</code>",
        reply_markup=pay_buttons(u.pay_code, price)
    )
    await call.answer()


# ================= INVITE LINK =================
async def send_invites(tg_id: int):
    g = await bot.create_chat_invite_link(
        GROUP_ID, member_limit=1,
        expire_date=datetime.utcnow() + timedelta(hours=1)
    )
    c = await bot.create_chat_invite_link(
        CHANNEL_ID, member_limit=1,
        expire_date=datetime.utcnow() + timedelta(hours=1)
    )
    await bot.send_message(
        tg_id,
        "✅ To‘lov tasdiqlandi!\n\n"
        f"👥 Guruh: {g.invite_link}\n"
        f"📣 Kanal: {c.invite_link}"
    )


# ================= 10s TEKSHIRUV =================
async def check_and_kick_if_no_subscription(chat_id: int, user_id: int):
    await asyncio.sleep(10)

    try:
        cm = await bot.get_chat_member(chat_id, user_id)
        if cm.status not in ("member", "administrator", "creator"):
            return
    except Exception:
        return

    async with Session() as s:
        sub = await s.get(Subscription, user_id)

    if not sub or not sub.active or sub.expires_at <= datetime.utcnow():
        try:
            await bot.ban_chat_member(chat_id, user_id)
            await bot.unban_chat_member(chat_id, user_id)
        except Exception:
            pass


@dp.chat_member()
async def on_chat_member_update(event: ChatMemberUpdated):
    if event.chat.id not in (GROUP_ID, CHANNEL_ID):
        return

    if event.old_chat_member.status in ("left", "kicked") and \
       event.new_chat_member.status in ("member", "administrator"):
        asyncio.create_task(
            check_and_kick_if_no_subscription(
                event.chat.id,
                event.new_chat_member.user.id
            )
        )


# ================= CRON =================
async def job_check_subs():
    subs = await get_active_subscriptions()
    now = datetime.utcnow()

    for sub in subs:
        if sub.expires_at <= now:
            for chat_id in (GROUP_ID, CHANNEL_ID):
                try:
                    await bot.ban_chat_member(chat_id, sub.tg_id)
                except Exception:
                    pass
            await deactivate_subscription(sub.tg_id)


# ================= STARTUP HELPERS =================
def setup_bot():
    register_admin(dp)


def start_scheduler(app):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(job_check_subs, "interval", hours=1)
    scheduler.start()
    app.state.scheduler = scheduler


async def stop_bot():
    await bot.session.close()
