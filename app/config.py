"""
Настройки приложения.
"""
import os

# Какую реализацию репозиториев использовать:
# "postgres" (по умолчанию) или "memory" (данные в оперативной памяти).
REPOSITORY = os.getenv("REPOSITORY", "postgres")
