from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        columns = await conn.run_sync(
            lambda sync_conn: {
                column["name"]
                for column in inspect(sync_conn).get_columns("appearance_features")
            }
        )
        if "aircraft_registration" not in columns:
            await conn.execute(
                text(
                    "ALTER TABLE appearance_features "
                    "ADD COLUMN aircraft_registration VARCHAR(32)"
                )
            )
        if "registration_confidence" not in columns:
            await conn.execute(
                text(
                    "ALTER TABLE appearance_features "
                    "ADD COLUMN registration_confidence FLOAT"
                )
            )
        policy_columns = await conn.run_sync(
            lambda sync_conn: {
                column["name"]
                for column in inspect(sync_conn).get_columns("recovery_policies")
            }
        )
        if "publish_idempotency_key" not in policy_columns:
            await conn.execute(
                text(
                    "ALTER TABLE recovery_policies "
                    "ADD COLUMN publish_idempotency_key VARCHAR(100)"
                )
            )
