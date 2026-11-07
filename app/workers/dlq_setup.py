"""Создание exchange, очередей и DLQ без запуска consumer'ов."""
import asyncio

from app.core.rabbitmq import declare_topology, get_connection


async def setup() -> None:
    connection = await get_connection()
    async with connection:
        channel = await connection.channel()
        await declare_topology(channel)
        print("DLQ настроена: kitchen_dlq, delivery_dlq, orders_dlq.", flush=True)


if __name__ == "__main__":
    asyncio.run(setup())
