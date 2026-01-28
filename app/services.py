from datetime import datetime, timedelta
import random
from sqlalchemy import select

from .database import Session
from .models import User, Subscription, Payment, Txn
from .config import PLAN_PRICES_UZS


# ---------- PLANS ----------
def normalize_plan_days(days: int) -> int:
    return days if days in (7, 30, 90) else 30

def expected_amount_uzs(plan_days: int) -> int:
    return PLAN_PRICES_UZS[normalize_plan_days(plan_days)]

def guess_plan_by_amount(amount_uzs: int):
    for d, p in PLAN_PRICES_UZS.items():
        if p == amount_uzs:
            return d
    return None


# ---------- PAY CODE ----------
def gen_pay_code() -> str:
    # 8 xonali faqat raqam
    return str(random.randint(10000000, 99999999))

async def _generate_unique_pay_code(s) -> str:
    # pay_code unique bo'lishi uchun tekshiradi
    while True:
        code = gen_pay_code()
        res = await s.execute(select(User).where(User.pay_code == code))
        if not res.scalars().first():
            return code


# ✅ MUHIM: BU FUNKSIYA PAY CODE'NI HECH QACHON "YANGILAMAYDI"
# faqat:
# 1) user yo'q bo'lsa -> yaratadi
# 2) user bor, lekin pay_code bo'sh bo'lsa -> bir marta to'ldiradi
async def ensure_user(tg_id: int) -> User:
    async with Session() as s:
        # ✅ 1) Avval tg_id bo'yicha qidiramiz (pk bo'lsa ham, bo'lmasa ham ishlaydi)
        res = await s.execute(select(User).where(User.tg_id == tg_id))
        u = res.scalars().first()

        if u:
            # pay_code tasodifan null/empty bo'lib qolsa, bir marta to'ldiramiz
            if not getattr(u, "pay_code", None):
                u.pay_code = await _generate_unique_pay_code(s)
                await s.commit()
            return u

        # ✅ 2) User yo'q bo'lsa — yangi user yaratamiz
        code = await _generate_unique_pay_code(s)
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


# ---------- SUBSCRIPTIONS ----------
async def upsert_subscription(tg_id: int, days: int):
    now = datetime.utcnow()
    days = normalize_plan_days(days)

    async with Session() as s:
        sub = await s.get(Subscription, tg_id)

        if sub and sub.active and sub.expires_at and sub.expires_at > now:
            sub.expires_at = sub.expires_at + timedelta(days=days)
        else:
            if not sub:
                sub = Subscription(
                    tg_id=tg_id,
                    expires_at=now + timedelta(days=days),
                    active=True
                )
                s.add(sub)
            else:
                sub.expires_at = now + timedelta(days=days)
                sub.active = True

                # warning flaglar bo'lsa reset
                if hasattr(sub, "warned_3d"):
                    sub.warned_3d = False
                if hasattr(sub, "warned_1d"):
                    sub.warned_1d = False
                if hasattr(sub, "last_renewal_notice"):
                    sub.last_renewal_notice = None

        await s.commit()
        return sub.expires_at


async def deactivate_subscription(tg_id: int):
    async with Session() as s:
        sub = await s.get(Subscription, tg_id)
        if sub:
            sub.active = False
            await s.commit()


# ---------- PAYMENTS ----------
async def add_payment(
    tg_id: int,
    provider: str,
    amount_uzs: int,
    status: str,
    plan_days: int,
    ext_id: str | None = None
):
    async with Session() as s:
        s.add(Payment(
            tg_id=tg_id,
            provider=provider,
            amount=amount_uzs,
            status=status,
            plan_days=plan_days,
            ext_id=ext_id
        ))
        await s.commit()


# ---------- ACTIVE SUBS ----------
async def get_active_subscriptions():
    async with Session() as s:
        res = await s.execute(select(Subscription).where(Subscription.active == True))
        return res.scalars().all()


# ---------- TXNS ----------
async def get_or_create_txn(provider: str, ext_id: str, tg_id: int, plan_days: int, amount_uzs: int):
    async with Session() as s:
        res = await s.execute(select(Txn).where(Txn.provider == provider, Txn.ext_id == ext_id))
        txn = res.scalars().first()
        if txn:
            return txn

        txn = Txn(
            provider=provider,
            ext_id=ext_id,
            tg_id=tg_id,
            plan_days=plan_days,
            amount_uzs=amount_uzs,
            state="created"
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
        if state == "performed" and hasattr(txn, "performed_at"):
            txn.performed_at = datetime.utcnow()

        await s.commit()
        return txn
