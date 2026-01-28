import re
from time import time
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException

from .config import (
    PUBLIC_BASE_URL, WEBHOOK_TOKEN,
    CLICK_SECRET, PAYME_SECRET,
    ALLOWED_WEBHOOK_IPS, PAYME_AMOUNT_MULTIPLIER
)
from .database import engine, Base
from .payments import verify_click_signature, verify_payme_basic_auth
from .services import (
    get_user_by_pay_code,
    upsert_subscription,
    add_payment,
    expected_amount_uzs,
    guess_plan_by_amount,
    get_or_create_txn,
    update_txn_state,
)
from .main import bot, dp, send_invites, setup_bot, start_scheduler, stop_bot
from aiogram.types import Update
from .main import setup_bot, start_scheduler


app = FastAPI()
_rate = {}


# ------------------- health -------------------
@app.get("/health")
async def health():
    return {"ok": True}
    
@app.on_event("startup")
async def on_startup():
    setup_bot()
    start_scheduler(app)

# ------------------- antifraud -------------------
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


# ------------------- telegram webhook -------------------
@app.post("/tg/webhook")
async def telegram_webhook(req: Request):
    data = await req.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}


# ------------------- click webhook -------------------
@app.post("/click/{token}")
async def click_webhook(token: str, req: Request):
    if token != WEBHOOK_TOKEN:
        raise HTTPException(status_code=404)

    anti_fraud_guard(req)
    data = await req.json()

    # test rejimda CLICK_SECRET="dummy" bo‘lsa sign tekshirmaydi
    if CLICK_SECRET != "dummy":
        if not verify_click_signature(data, CLICK_SECRET):
            return {"error": -1, "error_note": "Invalid signature"}

    action = int(data.get("action", 0))
    click_trans_id = str(data.get("click_trans_id", "")).strip()

    raw_code = str(data.get("merchant_trans_id", "")).strip()
    pay_code = re.sub(r"\D", "", raw_code)  # faqat raqam

    amount_uzs = int(float(data.get("amount", 0) or 0))

    if not pay_code:
        return {"error": -4, "error_note": "Empty PAY CODE"}

    u = await get_user_by_pay_code(pay_code)
    if not u:
        return {"error": -4, "error_note": "Invalid PAY CODE"}

    # plan aniqlash
    plan_days = int(data.get("plan_days", 0) or 0)
    if plan_days not in (7, 30, 90):
        guessed = guess_plan_by_amount(amount_uzs)
        if not guessed:
            return {"error": -2, "error_note": "Unknown plan by amount"}
        plan_days = guessed

    exp_amount = expected_amount_uzs(plan_days)
    if CLICK_SECRET != "dummy" and amount_uzs != exp_amount:
        return {"error": -2, "error_note": "Incorrect amount"}

    await get_or_create_txn("click", click_trans_id, u.tg_id, plan_days, amount_uzs)

    # action==0 (prepare), action==1 (perform)
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


# ------------------- payme webhook (JSON-RPC minimal) -------------------
@app.post("/payme/{token}")
async def payme_webhook(token: str, req: Request):
    if token != WEBHOOK_TOKEN:
        raise HTTPException(status_code=404)

    anti_fraud_guard(req)

    # prod rejimda basic auth kerak; testda PAYME_SECRET="dummy"
    if PAYME_SECRET != "dummy":
        if not verify_payme_basic_auth(req.headers, PAYME_SECRET):
            raise HTTPException(status_code=401, detail="Unauthorized")

    data = await req.json()
    method = data.get("method")
    params = data.get("params", {}) or {}

    # pay_code o‘qish
    account = params.get("account", {}) or {}
    raw = str(account.get("pay_code") or account.get("user_id") or "").strip()
    pay_code = re.sub(r"\D", "", raw)

    amount_tiyin = int(params.get("amount", 0) or 0)
    amount_uzs = amount_tiyin // PAYME_AMOUNT_MULTIPLIER if amount_tiyin else 0

    if not pay_code:
        return {"error": {"code": -31050, "message": "Empty PAY CODE"}}

    u = await get_user_by_pay_code(pay_code)
    if not u:
        return {"error": {"code": -31050, "message": "Invalid PAY CODE"}}

    plan_days = int(account.get("plan_days", 0) or 0)
    if plan_days not in (7, 30, 90):
        guessed = guess_plan_by_amount(amount_uzs)
        if not guessed:
            return {"error": {"code": -31001, "message": "Unknown plan by amount"}}
        plan_days = guessed

    exp_amount = expected_amount_uzs(plan_days)

    if method == "CheckPerformTransaction":
        if PAYME_SECRET != "dummy" and amount_uzs != exp_amount:
            return {"error": {"code": -31001, "message": "Incorrect amount"}}
        return {"result": {"allow": True}}

    if method == "PerformTransaction":
        payme_txn_id = str(params.get("id") or data.get("id") or "payme-txn")
        await get_or_create_txn("payme", payme_txn_id, u.tg_id, plan_days, amount_uzs)

        if PAYME_SECRET != "dummy" and amount_uzs != exp_amount:
            return {"error": {"code": -31001, "message": "Incorrect amount"}}

        await update_txn_state("payme", payme_txn_id, "performed")
        exp = await upsert_subscription(u.tg_id, plan_days)
        await add_payment(u.tg_id, "payme", amount_uzs, "success", plan_days, ext_id=payme_txn_id)
        await send_invites(u.tg_id)

        return {"result": {"transaction": payme_txn_id, "state": 2, "expires_at_utc": exp.isoformat()}}

    return {"error": {"code": -32601, "message": "Method not found"}}


# ------------------- startup/shutdown -------------------
@app.on_event("startup")
async def on_startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    setup_bot()

    # telegram webhook set
    if PUBLIC_BASE_URL:
        await bot.set_webhook(
            f"{PUBLIC_BASE_URL}/tg/webhook",
            allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"],
            drop_pending_updates=True
        )

    start_scheduler(app)


@app.on_event("shutdown")
async def on_shutdown():
    try:
        sch = getattr(app.state, "scheduler", None)
        if sch:
            sch.shutdown(wait=False)
    except Exception:
        pass
    await stop_bot()
