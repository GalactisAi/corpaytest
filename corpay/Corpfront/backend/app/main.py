from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from pathlib import Path
from contextlib import asynccontextmanager
import json
import os
from app.config import settings
from app.database import engine, Base, SessionLocal
from app.api import dashboard, auth, revenue, posts, employees, payments, system, config, slideshow
from app.models.user import User
import bcrypt

# Create database tables
Base.metadata.create_all(bind=engine)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def init_default_admin():
    """Initialize default admin user without destructive delete/reset."""
    auto_init = _env_bool("AUTO_INIT_ADMIN", default=(settings.environment != "production"))
    if not auto_init:
        print("Skipping default admin bootstrap (AUTO_INIT_ADMIN disabled)")
        return

    admin_email = (os.getenv("DEFAULT_ADMIN_EMAIL") or "admin@corpay.com").strip()
    admin_password = os.getenv("DEFAULT_ADMIN_PASSWORD") or "Cadmin@1"
    reset_password = _env_bool("ADMIN_RESET_PASSWORD_ON_STARTUP", default=False)

    db = SessionLocal()
    try:
        admin_user = db.query(User).filter(User.email == admin_email).first()
        password_hash = bcrypt.hashpw(admin_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

        if not admin_user:
            admin_user = User(
                email=admin_email,
                name="Admin User",
                password_hash=password_hash,
                is_admin=1,
            )
            db.add(admin_user)
            db.commit()
            print(f"Admin user created: {admin_email}")
        else:
            changed = False
            if not admin_user.is_admin:
                admin_user.is_admin = 1
                changed = True
            if reset_password:
                admin_user.password_hash = password_hash
                changed = True
            if changed:
                db.commit()
                print(f"Admin user updated: {admin_email}")
            else:
                print(f"Admin user already exists: {admin_email}")

    except Exception as e:
        print(f"ERROR: Could not initialize default admin user: {e}")
        import traceback

        traceback.print_exc()
        db.rollback()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan - start background tasks on startup"""
    # Initialize default admin user
    init_default_admin()

    # Clear newsroom cache so first request after restart gets fresh data (with dates)
    try:
        from app.utils.cache import delete
        for limit in (5, 12):
            delete(f"newsroom_{limit}")
    except Exception:
        pass

    yield


app = FastAPI(
    title="Dashboard API",
    description="Backend API for Corpay Dashboard",
    version="1.0.0",
    lifespan=lifespan
)

# Serve uploaded files statically
upload_dir = Path(settings.upload_dir)
upload_dir.mkdir(parents=True, exist_ok=True)
try:
    app.mount("/uploads", StaticFiles(directory=str(upload_dir)), name="uploads")
except Exception as e:
    print(f"Warning: Could not mount static files: {e}")

# CORS middleware: allow Railway/frontend origins; allow_methods=["*"] for OPTIONS preflight (avoids 400)
def _normalize_origin(value: str | None) -> str | None:
    """Return a trimmed origin string with protocol; None when empty."""
    if not value:
        return None
    v = value.strip().rstrip("/")
    if not v:
        return None
    if v.startswith(("http://", "https://")):
        return v
    # Assume https for bare domains such as foo.up.railway.app
    return f"https://{v}"


def _build_cors_origins() -> tuple[list[str], str | None]:
    """Merge defaults, env extras, and Railway/Vercel domains."""
    origins = {o for o in settings.cors_origins if o}

    extra_raw = (os.getenv("CORS_ORIGINS_EXTRA") or "").strip()
    if extra_raw:
        if extra_raw.startswith("["):
            try:
                parsed = json.loads(extra_raw)
                if isinstance(parsed, list):
                    for item in parsed:
                        origin = _normalize_origin(str(item) if item else None)
                        if origin:
                            origins.add(origin)
                else:
                    for part in extra_raw.split(","):
                        origin = _normalize_origin(part)
                        if origin:
                            origins.add(origin)
            except (json.JSONDecodeError, TypeError):
                for part in extra_raw.split(","):
                    origin = _normalize_origin(part)
                    if origin:
                        origins.add(origin)
        else:
            for part in extra_raw.split(","):
                origin = _normalize_origin(part)
                if origin:
                    origins.add(origin)

    for env_key in ("RAILWAY_PUBLIC_DOMAIN", "RAILWAY_STATIC_URL", "VERCEL_URL", "NEXT_PUBLIC_VERCEL_URL"):
        origin = _normalize_origin(os.getenv(env_key))
        if origin:
            origins.add(origin)

    # Optional escape hatch to trust all origins (useful for debugging misreported origins)
    if _env_bool("CORS_ALLOW_ALL", default=False):
        return [], ".*"

    # Allow any *.up.railway.app origin by default to cover preview/prod domains
    # Include both http and https to support preview links accessed without TLS during development.
    allow_regex = os.getenv("CORS_ALLOW_ORIGIN_REGEX") or r"https?://.*\.up\.railway\.app"
    return list(origins), allow_regex


_cors_allow_origins, _cors_allow_regex = _build_cors_origins()
print(f"[CORS] allow_origins={_cors_allow_origins} allow_origin_regex={_cors_allow_regex}")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins,
    allow_origin_regex=_cors_allow_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Debug middleware for revenue upload to trace CORS/status behaviour
@app.middleware("http")
async def debug_revenue_upload_middleware(request, call_next):
    debug_log_path = (os.getenv("APP_DEBUG_LOG_PATH") or "").strip()
    if request.url.path.startswith("/api/admin/revenue/upload-dev"):
        try:
            from datetime import datetime as _dt
            import json as _json
            payload = {
                "sessionId": "debug-session",
                "runId": "pre-fix",
                "hypothesisId": "H7",
                "location": "main.py:debug_revenue_upload_middleware:request",
                "message": "Incoming upload-dev request",
                "data": {
                    "method": request.method,
                    "path": request.url.path,
                    "origin": request.headers.get("origin"),
                },
                "timestamp": int(_dt.now().timestamp() * 1000),
            }
            if debug_log_path:
                with open(debug_log_path, "a", encoding="utf-8") as f:
                    f.write(_json.dumps(payload) + "\n")
        except Exception:
            pass

        response = await call_next(request)

        try:
            from datetime import datetime as _dt
            import json as _json
            payload = {
                "sessionId": "debug-session",
                "runId": "pre-fix",
                "hypothesisId": "H8",
                "location": "main.py:debug_revenue_upload_middleware:response",
                "message": "upload-dev response",
                "data": {
                    "status_code": response.status_code,
                    "aca_origin": response.headers.get("access-control-allow-origin"),
                },
                "timestamp": int(_dt.now().timestamp() * 1000),
            }
            if debug_log_path:
                with open(debug_log_path, "a", encoding="utf-8") as f:
                    f.write(_json.dumps(payload) + "\n")
        except Exception:
            pass

        return response

    return await call_next(request)

# Include routers
app.include_router(dashboard.router)
app.include_router(auth.router)
app.include_router(revenue.router)
app.include_router(posts.router)
app.include_router(employees.router)
app.include_router(payments.router)
app.include_router(system.router)
app.include_router(config.router)
app.include_router(slideshow.router)


@app.get("/")
async def root():
    return {"message": "Dashboard API", "docs": "/docs"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.get("/health/db")
async def health_db_check():
    """Railway-friendly DB health check endpoint with real query."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "ok"}
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"status": "unhealthy", "database": "down", "error": str(exc)},
        )

