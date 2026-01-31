# app/models.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column, Integer, BigInteger, DateTime, Boolean, String, Index
)
from .database import Base


class User(Base):
    __tablename__ = "users"

    # Telegram ID lar BIGINT bo‘lishi shart (int32 ga sig‘maydi)
    tg_id = Column(BigInteger, primary_key=True, autoincrement=False)
    pay_code = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=True)


class Subscription(Base):
    __tablename__ = "subscriptions"

    tg_id = Column(BigInteger, primary_key=True, autoincrement=False)
    expires_at = Column(DateTime, nullable=False)
    active = Column(Boolean, default=True, nullable=False)

    warned_3d = Column(Boolean, default=False, nullable=False)
    warned_1d = Column(Boolean, default=False, nullable=False)
    last_renewal_notice = Column(DateTime, nullable=True)


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tg_id = Column(BigInteger, index=True, nullable=False)
    provider = Column(String, index=True, nullable=False)

    amount = Column(Integer, default=0, nullable=False)
    status = Column(String, default="success", nullable=False)

    ext_id = Column(String, nullable=True)
    plan_days = Column(Integer, default=30, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Txn(Base):
    __tablename__ = "txns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String, index=True, nullable=False)
    ext_id = Column(String, index=True, nullable=False)

    tg_id = Column(BigInteger, index=True, nullable=False)
    plan_days = Column(Integer, default=30, nullable=False)
    amount_uzs = Column(Integer, default=0, nullable=False)

    state = Column(String, default="created", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    performed_at = Column(DateTime, nullable=True)


# provider + ext_id takror bo‘lmasin (dubl tranzaksiya bloklashga ham yordam beradi)
Index("ix_txns_provider_ext", Txn.provider, Txn.ext_id, unique=True)
