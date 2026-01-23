from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base

engine = create_async_engine("sqlite+aiosqlite:///db.sqlite3")
Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()
