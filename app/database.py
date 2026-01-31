import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = (os.getenv("DATABASE_URL", "") or "").strip()
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL env topilmadi")

# Render: postgres://... yoki postgresql://...
# Bizga kerak: postgresql+asyncpg://...
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()
