import re
import asyncio
from datetime import datetime, timedelta
from time import time

from fastapi import FastAPI, Request, HTTPException

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    Update, ChatMemberUpdated
)
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import (
    BOT_TOKEN, GROUP_ID, CHANNEL_ID,
    CLICK_SECRET, PAYME_SECRET, PUBLIC_BASE_URL,
    PLAN_PRICES_UZS, PAYME_AMOUNT_MULTIPLIER,
    WEBHOOK_TOKEN, ALLOWED_WEBHOOK_IPS,
    PAYME_PAY_URL, CLICK_PAY_URL
)
from .database import engine, Base, Session
from .admin import register_admin
from .payments import verify_click_signature, verify_payme_basic_auth
from .services import (
    ensure_user, get_user_by_pay_code,
    upsert_subscription, deactivate_subscription,
    add_payment, get_active_subscriptions,
    expected_amount_uzs, normalize_plan_days,
    guess_plan_by_amount,
    get_or_create_txn, update_txn_state
)
from .models import Subscription

# ================= BOT / APP =================
bot = Bot(BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()
app = FastAPI()

_rate = {}

# ================= HELPERS =================
def get_client_ip(req: Request) -> str:
    xff = req.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return req.client.host if req.client else "unknown"

def ip_allowed(req: Request) -> bool:
    if not ALLOWED_WEBHOOK_IPS:
        return True
    allowed = {ip.strip() for ip in ALLOWED_WEBHOOK_IPS.split(",") if ip.strip()}
    return get_client_ip(req) in allowed

def rate_limit_ok(ip: str, limit: int = 40, window: int = 60) -> bool:
    now = time()
    arr = _rate.get(ip, [])
    arr = [t for t in arr if now - t < window]
    if len(arr) >= limit:
        _rate[ip] = arr
        return False
    arr.append(now)
    _rate[ip] = arr
    return True

def anti_fraud_guard(req: Request):
    ip = get_client_ip(req)
    if not rate_limit_ok(ip):
        raise HTTPException(status_code=429, detail="Too many requests")
    if not ip_allowed(req):
        raise HTTPException(status_code=403, detail="IP not allowed")

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

# ================= USER COMMANDS =================
@dp.message(Command("start"))
async def start_cmd(msg: Message):
    u = await ensure_user(msg.from_user.id)
    await msg.answer(
        "💎 Pullik obuna\n\n"
        f"🔐 PAY CODE: <code>{u.pay_code}</code>\n"
        "Tarifni tanlang 👇",
        reply_markup=plans_keyboard()
    )

@dp.callback_query(F.data.startswith("plan:"))
async def choose_plan(call):
    u = await ensure_user(call.from_user.id)
    days = normalize_plan_days(int(call.data.split(":")[1]))
    price = expected_amount_uzs(days)

    await call.message.answer(
        f"✅ Tarif: {days} kun\n"
        f"💰 Narx: {price} so'm\n\n"
        "To‘lovda ID maydoniga shu PAY CODE ni yozing:\n"
        f"<code>{u.pay_code}</code>",
        reply_markup=pay_buttons(u.pay_code, price)
    )
    await call.answer()

# ================= INVITES =================
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
        f"📣 Kanal: {c.invite_link}\n\n"
        "⏳ Linklar 1 soat amal qiladi."
    )

# ================= 10 SONIYA TEKSHIRUV =================
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

# ================= 🔥 ASOSIY TEKSHIRUV (FAQAT CHAT_MEMBER) =================
@dp.chat_member()
async def on_chat_member_update(event: ChatMemberUpdated):
    chat_id = event.chat.id

    # faqat kerakli chatlar
    if chat_id not in (GROUP_ID, CHANNEL_ID):
        return

    old = event.old_chat_member.status
    new = event.new_chat_member.status

    # faqat KIRISH payti
    if old in ("left", "kicked") and new in ("member", "administrator"):
        user_id = event.new_chat_member.user.id
        asyncio.create_task(
            check_and_kick_if_no_subscription(chat_id, user_id)
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

# ================= WEBHOOKS =================
@app.post("/tg/webhook")
async def telegram_webhook(req: Request):
    data = await req.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}

# ================= STARTUP =================
@app.on_event("startup")
async def on_startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    register_admin(dp)

    await bot.set_webhook(
        f"{PUBLIC_BASE_URL}/tg/webhook",
        allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"],
        drop_pending_updates=True
    )

    scheduler = AsyncIOScheduler()
    scheduler.add_job(job_check_subs, "interval", hours=1)
    scheduler.start()
    app.state.scheduler = scheduler

@app.on_event("shutdown")
async def on_shutdown():
    await bot.session.close()
