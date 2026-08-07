from __future__ import annotations

import argparse
import asyncio
import json

from app.batch_rebuild import rebuild_normalized_batch
from app.db import SessionLocal, init_db


async def main(source_batch_id: int, strategy_id: int | None) -> None:
    await init_db()
    async with SessionLocal() as db:
        batch, run = await rebuild_normalized_batch(db, source_batch_id, strategy_id)
        print(
            json.dumps(
                {
                    "batch_id": batch.id,
                    "batch_name": batch.name,
                    "stats": batch.stats,
                    "run_id": run.id,
                    "metrics": run.metrics,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="从历史原始行重建驻位归一化批次")
    parser.add_argument("source_batch_id", type=int)
    parser.add_argument("--strategy-id", type=int)
    args = parser.parse_args()
    asyncio.run(main(args.source_batch_id, args.strategy_id))
