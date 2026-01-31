from __future__ import annotations

from sqlalchemy import (
    Column, BigInteger, Integer, DateTime, Boolean, String,
    ForeignKey, Index, func
)
from .database import Base


class User(Base):
    __tablename__ = "users"

    # Telegram ID -> BIGINT, auto-increment bo'lmasin!
    tg_id = Column(BigInteger, primary_key=True, autoincrement=False)

    # 1 user = 1 pay_code (umrbod)
    pay_code = Column(String(32), unique=True, index=True, nullable=False)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class Subscription(Base):
    __tablename__ = "subscriptions"

    tg_id = Column(
        BigInteger,
        ForeignKey("users.tg_id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )

    expires_at = Column(DateTime, nullable=False)
    active = Column(Boolean, server_default="true", nullable=False)

    warned_3d = Column(Boolean, server_default="false", nullable=False)
    warned_1d = Column(Boolean, server_default="false", nullable=False)

    last_renewal_notice = Column(DateTime, nullable=True)


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, autoincrement=True)

    tg_id = Column(
        BigInteger,
        ForeignKey("users.tg_id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    provider = Column(String(32), index=True, nullable=False)   # payme/click/admin/...
    amount = Column(Integer, server_default="0", nullable=False)
    status = Column(String(32), server_default="success", nullable=False)
    ext_id = Column(String(128), nullable=True)
    plan_days = Column(Integer, server_default="30", nullable=False)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class Txn(Base):
    __tablename__ = "txns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(32), index=True, nullable=False)
    ext_id = Column(String(128), nullable=False)

    tg_id = Column(
        BigInteger,
        ForeignKey("users.tg_id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    plan_days = Column(Integer, server_default="30", nullable=False)
    amount_uzs = Column(Integer, server_default="0", nullable=False)
    state = Column(String(32), server_default="created", nullable=False)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    performed_at = Column(DateTime, nullable=True)


# 1 ta transaction 2 marta ishlamasligi uchun:
Index("ix_txns_provider_ext", Txn.provider, Txn.ext_id, unique=True)
