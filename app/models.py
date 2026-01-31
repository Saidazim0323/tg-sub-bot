from sqlalchemy import Column, Integer, BigInteger, DateTime, Boolean, String, Index
from datetime import datetime
from .database import Base

class User(Base):
    __tablename__ = "users"
    tg_id = Column(BigInteger, primary_key=True)  # ✅ BIGINT
    pay_code = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Subscription(Base):
    __tablename__ = "subscriptions"
    tg_id = Column(BigInteger, primary_key=True)  # ✅ BIGINT
    expires_at = Column(DateTime, nullable=False)
    active = Column(Boolean, default=True)
    warned_3d = Column(Boolean, default=False)
    warned_1d = Column(Boolean, default=False)
    last_renewal_notice = Column(DateTime, nullable=True)

class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tg_id = Column(BigInteger, index=True)  # ✅ BIGINT
    provider = Column(String, index=True)
    amount = Column(Integer, default=0)
    status = Column(String, default="success")
    ext_id = Column(String, nullable=True)
    plan_days = Column(Integer, default=30)
    created_at = Column(DateTime, default=datetime.utcnow)

class Txn(Base):
    __tablename__ = "txns"
    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String, index=True)
    ext_id = Column(String, index=True)
    tg_id = Column(BigInteger, index=True)  # ✅ BIGINT
    plan_days = Column(Integer, default=30)
    amount_uzs = Column(Integer, default=0)
    state = Column(String, default="created")
    created_at = Column(DateTime, default=datetime.utcnow)
    performed_at = Column(DateTime, nullable=True)

Index("ix_txns_provider_ext", Txn.provider, Txn.ext_id, unique=True)
