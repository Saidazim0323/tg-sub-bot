from sqlalchemy import Column, Integer, DateTime, Boolean, String
from datetime import datetime
from .database import Base

class User(Base):
    __tablename__ = "users"
    tg_id = Column(Integer, primary_key=True)

class Subscription(Base):
    __tablename__ = "subscriptions"
    tg_id = Column(Integer, primary_key=True)
    expires_at = Column(DateTime)
    active = Column(Boolean, default=True)
    auto_renew = Column(Boolean, default=False)

class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer)
    provider = Column(String)
    amount = Column(Integer)
    status = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
