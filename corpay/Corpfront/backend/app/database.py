"""
Production-safe database configuration for FastAPI + SQLAlchemy + Supabase PostgreSQL.
Fixes SSL connection closed unexpectedly after Railway idle wake-up.
Tuned for Supabase Pro: larger pool and overflow to avoid QueuePool limit errors.
"""
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, Query
from typing import Generator
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from app.config import settings

# DATABASE_URL is loaded from environment (config.py loads .env and Settings.database_url)
# Also check DATABASE env var (Railway uses this name)
import os as _os
DATABASE_URL = (settings.database_url or "").strip() or _os.getenv("DATABASE_URL", "") or _os.getenv("DATABASE", "") or "sqlite:///./dashboard.db"

# Retry settings for transient SSL/connection drops (Supabase free tier)
_MAX_DB_RETRIES = 2  # max 2 retries = 3 total attempts


def _env_int(name: str, default: int) -> int:
    """Read positive integer env var with safe fallback."""
    raw = (_os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
        return value if value > 0 else default
    except ValueError:
        return default


def _ensure_sslmode_require(url: str) -> str:
    """Ensure Postgres URL always carries sslmode=require."""
    if not url.startswith("postgresql"):
        return url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["sslmode"] = "require"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _pg_engine(url: str):
    url = url.replace("pooler.supabase.com:5432", "pooler.supabase.com:6543")
    # Ensure psycopg2 driver is explicit
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    url = _ensure_sslmode_require(url)
    pool_size = _env_int("DB_POOL_SIZE", 15)
    max_overflow = _env_int("DB_MAX_OVERFLOW", 20)
    pool_timeout = _env_int("DB_POOL_TIMEOUT", 20)
    pool_recycle = _env_int("DB_POOL_RECYCLE", 1800)
    return create_engine(
        url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
        pool_pre_ping=True,
        pool_use_lifo=True,
        connect_args={
            "sslmode": "require",
            "connect_timeout": 10,
            "options": "-c statement_timeout=30000",
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 5,
            "keepalives_count": 3,
            "application_name": "corpay_dashboard",
        },
    )


def _sqlite_engine(url: str):
    """SQLite engine for local fallback."""
    return create_engine(
        url,
        connect_args={"check_same_thread": False},
        echo=False,
    )


if DATABASE_URL.startswith("postgresql"):
    engine = _pg_engine(DATABASE_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        print(f"WARNING: Startup DB connectivity check failed: {e}")
        print("App will continue - pool will reconnect on first request")
else:
    engine = _sqlite_engine(DATABASE_URL)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def _is_connection_error(exc: BaseException) -> bool:
    """True if the exception is a transient connection/SSL error worth retrying."""
    if isinstance(exc, OperationalError):
        return True
    msg = (getattr(exc, "message", "") or str(exc)).lower()
    return "ssl" in msg or "connection" in msg or "closed" in msg or "reset" in msg


class _RetryingSession:
    """
    Wraps a Session and retries execute/commit on OperationalError (e.g. SSL drop).
    Max 2 retries (3 attempts total) so the app can recover without returning 500.
    """

    def __init__(self, session: Session):
        self._session = session

    def execute(self, *args, **kwargs):
        last_exc = None
        for attempt in range(_MAX_DB_RETRIES + 1):
            try:
                return self._session.execute(*args, **kwargs)
            except Exception as e:
                if not _is_connection_error(e) or attempt == _MAX_DB_RETRIES:
                    raise
                last_exc = e
                try:
                    self._session.rollback()
                except Exception:
                    pass
        if last_exc is not None:
            raise last_exc

    def commit(self):
        last_exc = None
        for attempt in range(_MAX_DB_RETRIES + 1):
            try:
                return self._session.commit()
            except Exception as e:
                if not _is_connection_error(e) or attempt == _MAX_DB_RETRIES:
                    raise
                last_exc = e
                try:
                    self._session.rollback()
                except Exception:
                    pass
        if last_exc is not None:
            raise last_exc

    def query(self, *args, **kwargs) -> Query:
        """Bind query to this wrapper so execute() (and thus retries) are used."""
        return self._session.query(*args, **kwargs).with_session(self)

    def __getattr__(self, name):
        return getattr(self._session, name)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency: yield a DB session and close it immediately after the request.
    Uses try...finally so db.close() is always called. Rollback on exception so
    the connection is clean when returned to the pool. Session is wrapped with
    retry logic for transient OperationalErrors (e.g. SSL drops).
    """
    db = SessionLocal()
    try:
        yield _RetryingSession(db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
