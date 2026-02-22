"""
Production-safe database configuration for FastAPI + SQLAlchemy + Supabase PostgreSQL.
Fixes SSL connection closed unexpectedly after Railway idle wake-up.
Tuned for Supabase Pro: larger pool and overflow to avoid QueuePool limit errors.
"""
from sqlalchemy import create_engine, text, event
from sqlalchemy.exc import OperationalError, PendingRollbackError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, Query
from typing import Generator, Any
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from app.config import settings

# DATABASE_URL is loaded from environment (config.py loads .env and Settings.database_url)
# Also check DATABASE env var (Railway uses this name)
import os as _os
DATABASE_URL = (settings.database_url or "").strip() or _os.getenv("DATABASE_URL", "") or _os.getenv("DATABASE", "") or "sqlite:///./dashboard.db"

# Retry settings for transient SSL/connection drops (Supabase free tier)
_MAX_DB_RETRIES = 3  # max 3 retries = 4 total attempts


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


def _is_retryable(exc: BaseException) -> bool:
    """True if the exception is a transient connection/SSL/pending-rollback error worth retrying."""
    if isinstance(exc, (OperationalError, PendingRollbackError)):
        return True
    msg = (getattr(exc, "message", "") or str(exc)).lower()
    keywords = ("ssl", "connection", "closed", "reset", "pending rollback", "server closed", "broken pipe")
    return any(k in msg for k in keywords)


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

    def _invalidate_on_connection_error(ctx: Any) -> None:
        """If the error is retryable, invalidate the connection so the pool can replace it."""
        orig = getattr(ctx, "original_exception", None)
        sqla = getattr(ctx, "sqlalchemy_exception", None)
        if (orig and _is_retryable(orig)) or (sqla and _is_retryable(sqla)):
            conn = getattr(ctx, "connection", None)
            if conn is not None:
                conn.invalidate()

    event.listen(engine, "handle_error", _invalidate_on_connection_error)
else:
    engine = _sqlite_engine(DATABASE_URL)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class _RetryingQuery:
    """
    Rebuilds the query from scratch on each retry so a broken connection never
    poisons the Query object. Stores (session, entities, ops) and rebuilds via
    _build_query() before every terminal call.
    """

    def __init__(self, session: Session, entities: tuple, ops: list | None = None):
        self._session = session
        self._entities = entities
        self._ops = ops or []

    def _build_query(self) -> Query:
        q = self._session.query(*self._entities)
        for method_name, args, kwargs in self._ops:
            q = getattr(q, method_name)(*args, **kwargs)
        return q

    def _retry_terminal(self, fn_name: str, *args, **kwargs):
        last_exc = None
        for attempt in range(_MAX_DB_RETRIES + 1):
            try:
                q = self._build_query()
                return getattr(q, fn_name)(*args, **kwargs)
            except Exception as e:
                if not _is_retryable(e) or attempt == _MAX_DB_RETRIES:
                    raise
                last_exc = e
                try:
                    self._session.rollback()
                    self._session.expire_all()
                except Exception:
                    pass
        raise last_exc

    def _chain(self, method_name: str, *args, **kwargs) -> "_RetryingQuery":
        return _RetryingQuery(
            self._session,
            self._entities,
            self._ops + [(method_name, args, kwargs)],
        )

    # Terminal methods
    def first(self):
        return self._retry_terminal("first")

    def all(self):
        return self._retry_terminal("all")

    def one(self):
        return self._retry_terminal("one")

    def one_or_none(self):
        return self._retry_terminal("one_or_none")

    def count(self):
        return self._retry_terminal("count")

    def scalar(self):
        return self._retry_terminal("scalar")

    def delete(self, synchronize_session="evaluate"):
        return self._retry_terminal("delete", synchronize_session=synchronize_session)

    def update(self, values, synchronize_session="evaluate"):
        return self._retry_terminal("update", values, synchronize_session=synchronize_session)

    def __iter__(self):
        return iter(self._retry_terminal("all"))

    # Chaining methods
    def filter(self, *a, **kw):
        return self._chain("filter", *a, **kw)

    def filter_by(self, **kw):
        return self._chain("filter_by", **kw)

    def order_by(self, *a, **kw):
        return self._chain("order_by", *a, **kw)

    def limit(self, *a, **kw):
        return self._chain("limit", *a, **kw)

    def offset(self, *a, **kw):
        return self._chain("offset", *a, **kw)

    def join(self, *a, **kw):
        return self._chain("join", *a, **kw)

    def outerjoin(self, *a, **kw):
        return self._chain("outerjoin", *a, **kw)

    def with_entities(self, *a, **kw):
        return self._chain("with_entities", *a, **kw)

    def distinct(self, *a, **kw):
        return self._chain("distinct", *a, **kw)

    def group_by(self, *a, **kw):
        return self._chain("group_by", *a, **kw)

    def having(self, *a, **kw):
        return self._chain("having", *a, **kw)

    def options(self, *a, **kw):
        return self._chain("options", *a, **kw)

    def subquery(self, *a, **kw):
        return self._build_query().subquery(*a, **kw)

    def with_labels(self, *a, **kw):
        return self._chain("with_labels", *a, **kw)

    def __getattr__(self, name: str):
        return getattr(self._build_query(), name)


class _RetryingSession:
    """
    Wraps a Session and retries execute/commit on OperationalError/PendingRollbackError
    (e.g. SSL drop). On retry calls rollback() then expire_all() to clear stale cache.
    """

    def __init__(self, session: Session):
        self._session = session

    def _retry(self, fn, *args, **kwargs):
        last_exc = None
        for attempt in range(_MAX_DB_RETRIES + 1):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                if not _is_retryable(e) or attempt == _MAX_DB_RETRIES:
                    raise
                last_exc = e
                try:
                    self._session.rollback()
                    self._session.expire_all()
                except Exception:
                    pass
        if last_exc is not None:
            raise last_exc

    def execute(self, *args, **kwargs):
        return self._retry(self._session.execute, *args, **kwargs)

    def commit(self):
        return self._retry(self._session.commit)

    def query(self, *args, **kwargs) -> _RetryingQuery:
        return _RetryingQuery(self._session, args)

    # Delegated methods (no retry; caller can use execute/commit for retry when needed)
    def add(self, *args, **kwargs):
        return self._session.add(*args, **kwargs)

    def add_all(self, *args, **kwargs):
        return self._session.add_all(*args, **kwargs)

    def delete(self, *args, **kwargs):
        return self._session.delete(*args, **kwargs)

    def flush(self, *args, **kwargs):
        return self._session.flush(*args, **kwargs)

    def refresh(self, *args, **kwargs):
        return self._session.refresh(*args, **kwargs)

    def rollback(self, *args, **kwargs):
        return self._session.rollback(*args, **kwargs)

    def close(self, *args, **kwargs):
        return self._session.close(*args, **kwargs)

    def get(self, *args, **kwargs):
        return self._session.get(*args, **kwargs)

    def scalar(self, *args, **kwargs):
        return self._session.scalar(*args, **kwargs)

    def expire_all(self, *args, **kwargs):
        return self._session.expire_all(*args, **kwargs)

    def __getattr__(self, name: str):
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
