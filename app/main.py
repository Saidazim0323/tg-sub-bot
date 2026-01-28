import re
import asyncio
from datetime import datetime, timedelta
from time import time

from fastapi import FastAPI, Request, HTTPException

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, Update, ChatMemberUpdated
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

bot = Bot(BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()
app = FastAPI()

_rate = {}


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


def pay_buttons(pay_code: str, amount: int):
    rows = []
    if PAYME_PAY_URL:
        rows.append([InlineKeyboardButton(text="💳 Payme orqali to‘lash", url=PAYME_PAY_URL)])
    if CLICK_PAY_URL:
        rows.append([InlineKeyboardButton(text="💳 Click orqali to‘lash", url=CLICK_PAY_URL)])
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


def plans_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"7 kun — {PLAN_PRICES_UZS[7]} so'm", callback_data="plan:7")],
        [InlineKeyboardButton(text=f"30 kun — {PLAN_PRICES_UZS[30]} so'm", callback_data="plan:30")],
        [InlineKeyboardButton(text=f"90 kun — {PLAN_PRICES_UZS[90]} so'm", callback_data="plan:90")],
    ])


@dp.message(Command("start"))
async def start_cmd(msg: Message):
    u = await ensure_user(msg.from_user.id)
    await msg.answer(
        "💎 Pullik obuna.\n\n"
        f"🔐 Sizning PAY CODE: <code>{u.pay_code}</code>\n"
        "Tarifni tanlang 👇",
        reply_markup=plans_keyboard()
    )


@dp.message(Command("help"))
async def help_cmd(msg: Message):
    await msg.answer(
        "ℹ️ <b>Yordam</b>\n\n"
        "1️⃣ /start — PAY CODE olish va tarif tanlash\n\n"
        "2️⃣ To‘lov qilish:\n"
        "• Payme yoki Click ilovasiga kiring\n"
        "• Merchant nomini qidiring\n"
        "• <b>ID maydoniga PAY CODE</b> ni yozing\n"
        "• Tarif summasini kiriting\n\n"
        "3️⃣ To‘lovdan keyin:\n"
        "• Bot avtomatik guruh va kanal linkini yuboradi\n\n"
        "❓ Muammo bo‘lsa — adminga yozing"
    )


@dp.callback_query(F.data.startswith("plan:"))
async def choose_plan(call):
    u = await ensure_user(call.from_user.id)
    days = normalize_plan_days(int(call.data.split(":")[1]))
    price = expected_amount_uzs(days)

    kb = pay_buttons(u.pay_code, price)
    await call.message.answer(
        f"✅ Tanlangan tarif: {days} kun\n"
        f"💰 Narx: {price} so'm\n\n"
        "✅ Payme/Click to‘lovda ID maydoniga mana shuni yozing:\n"
        f"🔐 PAY CODE: <code>{u.pay_code}</code>\n\n"
        "To‘lov tasdiqlansa bot avtomatik link yuboradi.",
        reply_markup=kb
    )


async def send_invites(tg_id: int):
    g = await bot.create_chat_invite_link(
        chat_id=GROUP_ID,
        member_limit=1,
        expire_date=datetime.utcnow() + timedelta(hours=1),
    )
    c = await bot.create_chat_invite_link(
        chat_id=CHANNEL_ID,
        member_limit=1,
        expire_date=datetime.utcnow() + timedelta(hours=1),
    )
    await bot.send_message(
        tg_id,
        "✅ To‘lov tasdiqlandi!\n\n"
        f"👥 Guruh: {g.invite_link}\n"
        f"📣 Kanal: {c.invite_link}\n\n"
        "⏳ Linklar 1 soat amal qiladi va 1 martalik."
    )


# ✅ 10 soniya tekshiruv: begona kirsa chiqaradi
async def check_and_kick_if_no_subscription(chat_id: int, user_id: int):
    await asyncio.sleep(10)

    # Hali chat ichidami?
    try:
        cm = await bot.get_chat_member(chat_id, user_id)
        if cm.status not in ("member", "administrator", "creator"):
            return
    except Exception:
        return

    # Obuna aktivmi?
    async with Session() as s:
        sub = await s.get(Subscription, user_id)

    if not sub or not sub.active or sub.expires_at <= datetime.utcnow():
        try:
            await bot.ban_chat_member(chat_id, user_id)
            await bot.unban_chat_member(chat_id, user_id)
        except Exception:
            pass


# ✅ Guruh + kanalga kirganlarni ushlash
@dp.chat_member()
async def on_chat_member_update(event: ChatMemberUpdated):
    chat_id = event.chat.id
    if chat_id not in (GROUP_ID, CHANNEL_ID):
        return

    new_status = event.new_chat_member.status
    if new_status not in ("member", "administrator"):
        return

    user_id = event.new_chat_member.user.id
    asyncio.create_task(check_and_kick_if_no_subscription(chat_id, user_id))


async def job_check_subs():
    subs = await get_active_subscriptions()
    now = datetime.utcnow()

    for sub in subs:
        left = sub.expires_at - now
        if left.total_seconds() <= 0:
            try:
                await bot.ban_chat_member(GROUP_ID, sub.tg_id)
            except Exception:
                pass
            try:
                await bot.ban_chat_member(CHANNEL_ID, sub.tg_id)
            except Exception:
                pass

            await deactivate_subscription(sub.tg_id)
            try:
                await bot.send_message(sub.tg_id, "❌ Obuna tugadi. /start bosing.")
            except Exception:
                pass
            continue

        async with Session() as s:
            db_sub = await s.get(Subscription, sub.tg_id)
            if not db_sub:
                continue

            if left <= timedelta(days=3) and not db_sub.warned_3d:
                try:
                    await bot.send_message(sub.tg_id, "⏳ Obuna tugashiga 3 kun qoldi.")
                except Exception:
                    pass
                db_sub.warned_3d = True

            if left <= timedelta(days=1) and not db_sub.warned_1d:
                try:
                    await bot.send_message(sub.tg_id, "⚠️ Obuna tugashiga 1 kun qoldi.")
                except Exception:
                    pass
                db_sub.warned_1d = True

            await s.commit()


@app.post("/tg/webhook")
async def telegram_webhook(req: Request):
    data = await req.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}


@app.post("/click/{token}")
async def click_webhook(token: str, req: Request):
    if token != WEBHOOK_TOKEN:
        raise HTTPException(status_code=404)

    anti_fraud_guard(req)
    data = await req.json()

    if CLICK_SECRET != "dummy":
        if not verify_click_signature(data, CLICK_SECRET):
            return {"error": -1, "error_note": "Invalid signature"}

    action = int(data.get("action", 0))
    click_trans_id = str(data.get("click_trans_id", "")).strip()

    raw_code = str(data.get("merchant_trans_id", "")).strip()
    pay_code = re.sub(r"\D", "", raw_code)

    amount_uzs = int(float(data.get("amount", 0)))

    if not pay_code:
        return {"error": -4, "error_note": "Empty PAY CODE"}

    u = await get_user_by_pay_code(pay_code)
    if not u:
        return {"error": -4, "error_note": "Invalid PAY CODE"}

    plan_days = int(data.get("plan_days", 0) or 0)
    if plan_days not in (7, 30, 90):
        guessed = guess_plan_by_amount(amount_uzs)
        if not guessed:
            try:
                await bot.send_message(u.tg_id, "❌ Summa tarifga mos emas.")
            except Exception:
                pass
            return {"error": -2, "error_note": "Unknown plan by amount"}
        plan_days = guessed

    exp_amount = expected_amount_uzs(plan_days)

    if CLICK_SECRET != "dummy" and amount_uzs != exp_amount:
        try:
            await bot.send_message(u.tg_id, f"❌ Summa xato. Kerakli: {exp_amount}, keldi: {amount_uzs}")
        except Exception:
            pass
        return {"error": -2, "error_note": "Incorrect amount"}

    await get_or_create_txn("click", click_trans_id, u.tg_id, plan_days, amount_uzs)

    if action == 0:
        await update_txn_state("click", click_trans_id, "prepared")
        return {"error": 0, "error_note": "Success"}

    if action == 1:
        await update_txn_state("click", click_trans_id, "performed")
        exp = await upsert_subscription(u.tg_id, plan_days)
        await add_payment(u.tg_id, "click", amount_uzs, "success", plan_days, ext_id=click_trans_id)
        await send_invites(u.tg_id)
        return {"error": 0, "error_note": "Success", "expires_at_utc": exp.isoformat()}

    return {"error": -3, "error_note": "Unknown action"}


@app.post("/payme/{token}")
async def payme_webhook(token: str, req: Request):
    if token != WEBHOOK_TOKEN:
        raise HTTPException(status_code=404)

    anti_fraud_guard(req)

    if PAYME_SECRET != "dummy":
        if not verify_payme_basic_auth(req.headers, PAYME_SECRET):
            raise HTTPException(status_code=401, detail="Unauthorized")

    data = await req.json()
    method = data.get("method")
    params = data.get("params", {}) or {}

    def read_account():
        account = params.get("account", {}) or {}
        raw = str(account.get("user_id") or account.get("pay_code") or "").strip()
        pay_code_ = re.sub(r"\D", "", raw)
        plan_days_ = int(account.get("plan_days", 0) or 0)
        return pay_code_, plan_days_

    amount_tiyin = int(params.get("amount", 0) or 0)
    amount_uzs = amount_tiyin // PAYME_AMOUNT_MULTIPLIER if amount_tiyin else 0

    if method in ("CheckPerformTransaction", "CreateTransaction", "PerformTransaction"):
        pay_code, plan_days = read_account()
        if not pay_code:
            return {"error": {"code": -31050, "message": "Empty PAY CODE"}}

        u = await get_user_by_pay_code(pay_code)
        if not u:
            return {"error": {"code": -31050, "message": "Invalid PAY CODE"}}

        if plan_days not in (7, 30, 90):
            guessed = guess_plan_by_amount(amount_uzs)
            if not guessed:
                try:
                    await bot.send_message(u.tg_id, "❌ Summa tarifga mos emas.")
                except Exception:
                    pass
                return {"error": {"code": -31001, "message": "Unknown plan by amount"}}
            plan_days = guessed

        exp_amount = expected_amount_uzs(plan_days)

    if method == "CheckPerformTransaction":
        if PAYME_SECRET != "dummy" and amount_uzs != exp_amount:
            return {"error": {"code": -31001, "message": "Incorrect amount"}}
        return {"result": {"allow": True}}

    if method == "PerformTransaction":
        payme_txn_id = str(params.get("id") or data.get("id"))
        await get_or_create_txn("payme", payme_txn_id, u.tg_id, plan_days, amount_uzs)

        if PAYME_SECRET != "dummy" and amount_uzs != exp_amount:
            try:
                await bot.send_message(u.tg_id, f"❌ Summa xato. Kerakli:{exp_amount}, keldi:{amount_uzs}")
            except Exception:
                pass
            return {"error": {"code": -31001, "message": "Incorrect amount"}}

        await update_txn_state("payme", payme_txn_id, "performed")
        exp = await upsert_subscription(u.tg_id, plan_days)
        await add_payment(u.tg_id, "payme", amount_uzs, "success", plan_days, ext_id=payme_txn_id)
        await send_invites(u.tg_id)

        return {"result": {"transaction": payme_txn_id, "state": 2, "expires_at_utc": exp.isoformat()}}

    return {"error": {"code": -32601, "message": "Method not found"}}


@app.on_event("startup")
async def on_startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    register_admin(dp)

    if PUBLIC_BASE_URL:
        try:
            await bot.set_webhook(f"{PUBLIC_BASE_URL}/tg/webhook")
        except Exception:
            pass

    scheduler = AsyncIOScheduler()
    scheduler.add_job(job_check_subs, "interval", hours=1)
    scheduler.start()
    app.state.scheduler = scheduler


@app.on_event("shutdown")
async def on_shutdown():
    try:
        await bot.session.close()
    except Exception:
        pass
