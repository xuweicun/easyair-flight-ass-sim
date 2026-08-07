from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
from contextlib import suppress
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.routes import router
from app.seed import seed_demo
from app.recovery import (
    pending_recovery_run_ids,
    process_delivery_outbox,
    process_recovery_cycle,
)


logger = logging.getLogger(__name__)


async def recovery_scheduler(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=15)
            continue
        except TimeoutError:
            pass
        async with SessionLocal() as db:
            run_ids = await pending_recovery_run_ids(db)
            for run_id in run_ids:
                try:
                    await process_recovery_cycle(db, run_id)
                except LookupError:
                    continue
                except Exception:
                    await db.rollback()
                    logger.exception(
                        "运行%s的航班恢复调度失败，将在下个周期重试", run_id
                    )
            try:
                await process_delivery_outbox(db)
            except Exception:
                await db.rollback()
                logger.exception("出站预览调度失败，将在下个周期重试")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    async with SessionLocal() as db:
        await seed_demo(db)
        try:
            await process_recovery_cycle(db)
            await process_delivery_outbox(db)
        except LookupError:
            pass
    stop = asyncio.Event()
    scheduler = asyncio.create_task(recovery_scheduler(stop))
    try:
        yield
    finally:
        stop.set()
        scheduler.cancel()
        with suppress(asyncio.CancelledError):
            await scheduler


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
