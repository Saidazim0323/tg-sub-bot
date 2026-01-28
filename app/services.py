from datetime import datetime, timedelta
import random
from sqlalchemy import select

from .database import Session
from .models import User, Subscription, Payment, Txn
from .config import PLAN_PRICES_UZS

from datetime import datetime, timedelta, date
from sqlalchemy import select
from .database import Session
from .models import Payment, User


async def list_payments_since(dt_utc: datetime):
    async with Session() as s:
        q = (
            select(Payment, User.pay_code)
            .join(User, User.tg_id == Payment.tg_id, isouter=True)
            .where(Payment.created_at >= dt_utc)
            .order_by(Payment.id.desc())
        )
        res = await s.execute(q)
        out = []
        for p, pay_code in res.all():
            out.append({
                "id": p.id,
                "created_at": p.created_at,
                "tg_id": p.tg_id,
                "pay_code": pay_code,
                "provider": p.provider,
                "amount": p.amount,
                "status": p.status,
                "plan_days": getattr(p, "plan_days", 30),
                "ext_id": getattr(p, "ext_id", None),
            })
        return out


async def list_payments_today_utc():
    now = datetime.utcnow()
    start = datetime(now.year, now.month, now.day)  # UTC today 00:00
    return await list_payments_since(start)


async def list_payments_last_30d():
    start = datetime.utcnow() - timedelta(days=30)
    return await list_payments_since(start)

def normalize_plan_days(days: int) -> int:
    return days if days in (7, 30, 90) else 30

def expected_amount_uzs(plan_days: int) -> int:
    return PLAN_PRICES_UZS[normalize_plan_days(plan_days)]

def guess_plan_by_amount(amount_uzs: int):
    for d, p in PLAN_PRICES_UZS.items():
        if p == amount_uzs:
            return d
    return None


def gen_pay_code() -> str:
    return str(random.randint(10000000, 99999999))  # 8 xonali


async def ensure_user(tg_id: int) -> User:
    async with Session() as s:
        # ✅ tg_id PRIMARY KEY bo'lgani uchun get() ideal ishlaydi
        u = await s.get(User, tg_id)
        if u:
            return u

        # ✅ unique pay_code
        while True:
            code = gen_pay_code()
            res = await s.execute(select(User).where(User.pay_code == code))
            if not res.scalars().first():
                break

        u = User(tg_id=tg_id, pay_code=code)
        s.add(u)
        await s.commit()
        return u


async def get_user_by_pay_code(pay_code: str):
    pay_code = (pay_code or "").strip()
    if not pay_code:
        return None
    async with Session() as s:
        res = await s.execute(select(User).where(User.pay_code == pay_code))
        return res.scalars().first()


async def upsert_subscription(tg_id: int, days: int):
    now = datetime.utcnow()
    days = normalize_plan_days(days)

    async with Session() as s:
        sub = await s.get(Subscription, tg_id)
        if sub and sub.active and sub.expires_at > now:
            sub.expires_at = sub.expires_at + timedelta(days=days)
        else:
            if not sub:
                sub = Subscription(tg_id=tg_id, expires_at=now + timedelta(days=days), active=True)
                s.add(sub)
            else:
                sub.expires_at = now + timedelta(days=days)
                sub.active = True
                sub.warned_3d = False
                sub.warned_1d = False
                sub.last_renewal_notice = None
        await s.commit()
        return sub.expires_at


async def deactivate_subscription(tg_id: int):
    async with Session() as s:
        sub = await s.get(Subscription, tg_id)
        if sub:
            sub.active = False
            await s.commit()


async def add_payment(
    tg_id: int, provider: str, amount_uzs: int, status: str,
    plan_days: int, ext_id: str | None = None
):
    async with Session() as s:
        s.add(Payment(
            tg_id=tg_id, provider=provider, amount=amount_uzs,
            status=status, plan_days=plan_days, ext_id=ext_id
        ))
        await s.commit()


async def get_active_subscriptions():
    async with Session() as s:
        res = await s.execute(select(Subscription).where(Subscription.active == True))
        return res.scalars().all()


async def get_or_create_txn(provider: str, ext_id: str, tg_id: int, plan_days: int, amount_uzs: int):
    async with Session() as s:
        res = await s.execute(select(Txn).where(Txn.provider == provider, Txn.ext_id == ext_id))
        txn = res.scalars().first()
        if txn:
            return txn

        txn = Txn(
            provider=provider, ext_id=ext_id, tg_id=tg_id,
            plan_days=plan_days, amount_uzs=amount_uzs, state="created"
        )
        s.add(txn)
        await s.commit()
        return txn


async def update_txn_state(provider: str, ext_id: str, state: str):
    async with Session() as s:
        res = await s.execute(select(Txn).where(Txn.provider == provider, Txn.ext_id == ext_id))
        txn = res.scalars().first()
        if not txn:
            return None
        txn.state = state
        if state == "performed":
            txn.performed_at = datetime.utcnow()
        await s.commit()
        return txn
