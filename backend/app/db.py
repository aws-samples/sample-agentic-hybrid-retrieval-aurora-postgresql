from __future__ import annotations
import psycopg
from psycopg.rows import dict_row
from .config import get_settings

def get_conn(row_factory=None):
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not set. For local development use postgresql://localhost:55432/retrieval?sslmode=disable")
    return psycopg.connect(settings.database_url, autocommit=True, row_factory=row_factory)

def get_dict_conn():
    return get_conn(row_factory=dict_row)
