import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer

from app import main
from app.core.config import settings
from app.database import get_db
from app.modules.orders import service as orders_service

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def postgres():
    # Та же версия и расширение vector, что в docker-compose.yml.
    with PostgresContainer("pgvector/pgvector:pg15") as container:
        url = container.get_connection_url()
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT,
            env={**os.environ, "DATABASE_URL": url},
            check=True,
        )
        engine = create_engine(url)
        try:
            yield engine
        finally:
            engine.dispose()


@pytest.fixture
def db_sessions(postgres):
    # HTTP-запросы коммитят изменения. Удаляем строки, включая связанные
    # данные, только из временного контейнера, сохраняя роли и категории Alembic.
    try:
        yield sessionmaker(bind=postgres, autoflush=False)
    finally:
        with postgres.begin() as connection:
            connection.execute(text("TRUNCATE users, menu_items, orders RESTART IDENTITY CASCADE"))


@pytest.fixture
def client(db_sessions, monkeypatch):
    def get_test_db():
        with db_sessions() as session:
            yield session

    monkeypatch.setitem(main.app.dependency_overrides, get_db, get_test_db)
    monkeypatch.setattr(settings, "REPOSITORY", "postgres")
    monkeypatch.setattr(main, "warm_up_menu_cache", Mock())
    # Публикация фоновых задач находится за границей этого теста.
    for task in (
        orders_service.generate_order_pdf,
        orders_service.send_order_email,
        orders_service.send_order_sms,
    ):
        monkeypatch.setattr(task, "delay", Mock())

    with TestClient(main.app) as http:
        yield http
