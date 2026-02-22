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
_origins = list(settings.cors_origins)
_extra = (os.getenv("CORS_ORIGINS_EXTRA") or "").strip()
if _extra:
    if _extra.startswith("["):
        try:
            _parsed = json.loads(_extra)
            if isinstance(_parsed, list):
                _origins.extend(str(o).strip() for o in _parsed if o and str(o).strip())
            else:
                _origins.extend(o.strip() for o in _extra.split(",") if o.strip())
        except (json.JSONDecodeError, TypeError):
            _origins.extend(o.strip() for o in _extra.split(",") if o.strip())
    else:
        _origins.extend(o.strip() for o in _extra.split(",") if o.strip())
if os.getenv("RAILWAY_PUBLIC_DOMAIN"):
    _railway_origin = f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}"
    if _railway_origin not in _origins:
        _origins.append(_railway_origin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
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

