"""Postgres/Supabase connection helpers for Study Desk."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL (or SUPABASE_DB_URL) must be set to a Postgres/Supabase "
        "connection string, e.g. postgresql://postgres:<pw>@db.<ref>.supabase.co:5432/postgres"
    )


_pool: Optional[ConnectionPool] = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=DATABASE_URL,
            min_size=1,
            max_size=int(os.getenv("DB_POOL_MAX", "10")),
            kwargs={"row_factory": dict_row, "autocommit": True},
            open=True,
        )
    return _pool


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    with get_pool().connection() as conn:
        yield conn


@contextmanager
def cursor(*, transaction: bool = False) -> Iterator[psycopg.Cursor]:
    with get_pool().connection() as conn:
        if transaction:
            conn.autocommit = False
            try:
                with conn.cursor() as cur:
                    yield cur
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.autocommit = True
        else:
            with conn.cursor() as cur:
                yield cur


def init_schema() -> None:
    """Apply schema.sql (idempotent)."""
    sql = Path(__file__).with_name("schema.sql").read_text()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
