"""
Production-safe database configuration for FastAPI + SQLAlchemy + Supabase PostgreSQL.
Fixes SSL connection closed unexpectedly after Railway idle wake-up.
Tuned for Supabase Pro: larger pool and overflow to avoid QueuePool limit errors.
"""
import base64
import logging
import tempfile
import threading
import time
from time import perf_counter
from typing import Any, Generator
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError, PendingRollbackError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Query, Session, sessionmaker

from app.config import settings

logger = logging.getLogger("db.timing")

# DATABASE_URL is loaded from environment (config.py loads .env and Settings.database_url)
# Also check DATABASE env var (Railway uses this name)
import os as _os
DATABASE_URL = (settings.database_url or "").strip() or _os.getenv("DATABASE_URL", "") or _os.getenv("DATABASE", "") or "sqlite:///./dashboard.db"

# Retry settings for transient SSL/connection drops (tunable via env, e.g., DB_MAX_RETRIES=3 for Pro)
_MAX_DB_RETRIES = int(_os.getenv("DB_MAX_RETRIES", "5") or 5)


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
    # Small pool: fewer dead connections to recycle after long idle periods.
    # Override via env DB_POOL_SIZE / DB_MAX_OVERFLOW / DB_POOL_TIMEOUT / DB_POOL_RECYCLE
    pool_size = _env_int("DB_POOL_SIZE", 5)
    max_overflow = _env_int("DB_MAX_OVERFLOW", 10)
    pool_timeout = _env_int("DB_POOL_TIMEOUT", 45)
    # Recycle every 60 s — well before Supabase's ~5-minute idle-kill timeout.
    # This proactively replaces stale connections so SSL drops never reach queries.
    pool_recycle = _env_int("DB_POOL_RECYCLE", 60)  # seconds

    connect_args = {
        "sslmode": "require",
        "connect_timeout": 15,
        "options": "-c statement_timeout=30000",
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 5,
        "keepalives_count": 3,
        "application_name": "corpay_dashboard",
    }

    # Supabase CA cert for verify-ca: set SUPABASE_CA_CERT to base64-encoded PEM (or use default)
    ca_b64 = _os.getenv(
        "SUPABASE_CA_CERT",
        "LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCk1JSUR4RENDQXF5Z0F3SUJBZ0lVYkx4TW9kNjJQMmt0Q2lBa3huS0p3dEU5VlBZd0RRWUpLb1pJaHZjTkFRRUwKQlFBd2F6RUxNQWtHQTFVRUJoTUNWVk14RURBT0JnTlZCQWdNQjBSbGJIZGhjbVV4RXpBUkJnTlZCQWNNQ2s1bApkeUJEWVhOMGJHVXhGVEFUQmdOVkJBb01ERk4xY0dGaVlYTmxJRWx1WXpFZU1Cd0dBMVVFQXd3VlUzVndZV0poCmMyVWdVbTl2ZENBeU1ESXhJRU5CTUI0WERUSXhNRFF5T0RFd05UWTFNMW9YRFRNeE1EUXlOakV3TlRZMU0xb3cKYXpFTE1Ba0dBMVVFQmhNQ1ZWTXhFREFPQmdOVkJBZ01CMFJsYkhkaGNtVXhFekFSQmdOVkJBY01DazVsZHlCRApZWE4wYkdVeEZUQVRCZ05WQkFvTURGTjFjR0ZpWVhObElFbHVZekVlTUJ3R0ExVUVBd3dWVTNWd1lXSmhjMlVnClVtOXZkQ0F5TURJeElFTkJNSUlCSWpBTkJna3Foa2lHOXcwQkFRRUZBQU9DQVE4QU1JSUJDZ0tDQVFFQXFRWFcKUXlIT0IrcVIyR0pvYkNxL0NCbVE0MEcwb0RtQ0MzbXpWbm44c3Y0WE5lV3RFNVhjRUwwdVZpaDdKbzREa3gxUQpEbUdIQkgxekRmZ3MycVhpTGI2eHB3L0NLUVB5cFpXMUpzc09UTUlmUXBwTlE4N0s3NVlhMHAyNVkzZVBTMnQyCkd0dkh4TmpVVjZrak9aakVuMnlXRWNCZHBPVkNVWUJWRkJOTUI0WUJIa05SRGEvK1M0dXl3QW9hVFduQ0pMVWkKY3ZUbEhtTXc2eFNRUW4xVWZSUUhrNTBETUNFSjdDeTFSeHJaSnJrWFhSUDNMcVFMMmlqSjZGNHlNZmgrR3liNApPNFhham9Wai8rUjRHd3l3S1lyclM4UHJTTnR3eHI1U3RsUU84eklRVVNNaXEyNndNOG1nRUxGbFMvMzJVY2x0Ck5hUTF4QlJpemt6cFpjdDlEd0lEQVFBQm8yQXdYakFMQmdOVkhROEVCQU1DQVFZd0hRWURWUjBPQkJZRUZLalgKdVhZMzJDenRraEltbmc0eUpOVXRhVVlzTUI4R0ExVWRJd1FZTUJhQUZLalh1WFkzMkN6dGtoSW1uZzR5Sk5VdAphVVlzTUE4R0ExVWRFd0VCL3dRRk1BTUJBZjh3RFFZSktvWklodmNOQVFFTEJRQURnZ0VCQUI4c3B6Tm4rNFZVCnRWeGJkTWFYKzM5WjUwc2M3dUFUbXVzMTZqbW1IamhJSHorbC85R2xKNUtxQU1PeDI2bVBaZ2Z6RzdvbmVMMmIKVlcrV2dZVWtUVDNYRVBGV25UcDJSSndRYW84L3RZUFhXRUpEYzBXVlFIcnBtbldPRktVL2QzTXFCZ0JtNXkrNgpqQjgxVFUvUkcyclZlclBEV1ArMU1NY05OeTA0OTFDVEw1WFFaN0pmREpKOUNDbVhTZHRUbDR1VVFuU3V2L1F4CkNlYTEzQlgyWmdKYzdBdTMwdmloTGh1YjUyRGU0UC80Z29uS3NOSFlkYldqZzdPV0t3TnYveml0R0RWREI5WTIKQ01UeVpLRzNYRXU1R2hsMUxFbkkzUW1FS3NxYUNMdjEyQm5WamJrU2Vac01uZXZKUHMxWWU2VGpqSndkaWs1UApvL2JLaUl6K0ZxOD0KLS0tLS1FTkQgQ0VSVElGSUNBVEUtLS0tLQo=",
    )
    if ca_b64:
        cert_bytes = base64.b64decode(ca_b64)
        tmpfile = tempfile.NamedTemporaryFile(delete=False, suffix=".crt")
        tmpfile.write(cert_bytes)
        tmpfile.close()
        connect_args["sslrootcert"] = tmpfile.name
        connect_args["sslmode"] = "verify-ca"

    return create_engine(
        url,
        use_native_hstore=False,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
        pool_pre_ping=True,
        pool_use_lifo=True,
        connect_args=connect_args,
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
            else:
                try:
                    engine.dispose()
                except Exception:
                    pass

    event.listen(engine, "handle_error", _invalidate_on_connection_error)
else:
    engine = _sqlite_engine(DATABASE_URL)

# Rate-limited pool disposal: prevents concurrent retries from disposing each
# other's freshly-opened connections (thundering-herd dispose storm).
_dispose_lock = threading.Lock()
_last_dispose_time: list[float] = [0.0]


def _safe_dispose() -> None:
    """Dispose the engine pool at most once every 2 s across all threads."""
    now = time.monotonic()
    with _dispose_lock:
        if now - _last_dispose_time[0] >= 2.0:
            try:
                engine.dispose()
            except Exception:
                pass
            _last_dispose_time[0] = time.monotonic()


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
                stmt = getattr(q, "statement", None)
                should_time = _is_select_statement(stmt)
                start = perf_counter() if should_time else None
                result = getattr(q, fn_name)(*args, **kwargs)
                if should_time and start is not None:
                    target_stmt = stmt if stmt is not None else q
                    _log_query_timing(target_stmt, perf_counter() - start, attempt)
                return result
            except Exception as e:
                if not _is_retryable(e) or attempt == _MAX_DB_RETRIES:
                    raise
                last_exc = e
                try:
                    self._session.rollback()
                except Exception:
                    pass
                try:
                    self._session.expire_all()
                except Exception:
                    pass
                try:
                    self._session.close()
                except Exception:
                    pass
                _safe_dispose()
                time.sleep(0.5 * (attempt + 1))
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

    def scalar_subquery(self, *a, **kw):
        return self._build_query().scalar_subquery(*a, **kw)

    def with_labels(self, *a, **kw):
        return self._chain("with_labels", *a, **kw)

    def __getattr__(self, name: str):
        return getattr(self._build_query(), name)


def _is_select_statement(stmt) -> bool:
    """Best-effort check to log only SELECT/read queries."""
    try:
        if bool(getattr(stmt, "is_select", False)):
            return True
        sql = str(stmt).lstrip().lower()
        return sql.startswith("select")
    except Exception:
        return False


def _log_query_timing(stmt, duration_seconds: float, attempt: int) -> None:
    """
    Emit a concise log for query duration. Avoid huge logs by truncating SQL text.
    attempt is 0-indexed from the retry loop.
    """
    try:
        sql = str(stmt).strip().replace("\n", " ")
        if len(sql) > 500:
            sql = sql[:500] + "..."
    except Exception:
        sql = "<unserializable statement>"
    logger.info(
        "[DB] select completed in %.2f ms (attempt %d) sql=%s",
        duration_seconds * 1000.0,
        attempt + 1,
        sql,
    )


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
            stmt = args[0] if args else kwargs.get("statement")
            should_time = fn is self._session.execute and _is_select_statement(stmt)
            start = perf_counter() if should_time else None
            try:
                result = fn(*args, **kwargs)
                if should_time and start is not None:
                    _log_query_timing(stmt, perf_counter() - start, attempt)
                return result
            except Exception as e:
                if not _is_retryable(e) or attempt == _MAX_DB_RETRIES:
                    raise
                last_exc = e
                try:
                    self._session.rollback()
                except Exception:
                    pass
                try:
                    self._session.expire_all()
                except Exception:
                    pass
                try:
                    self._session.close()
                except Exception:
                    pass
                _safe_dispose()
                time.sleep(0.5 * (attempt + 1))
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
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            db.close()
        except Exception:
            pass
