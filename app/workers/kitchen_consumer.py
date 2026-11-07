"""Независимый consumer кухни."""
import asyncio

from app.workers.consumer import run_consumer


if __name__ == "__main__":
    asyncio.run(run_consumer("kitchen"))
