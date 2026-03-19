from pathlib import Path
import os

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

# Load backend .env so DATABASE_URL is set when app runs from any cwd
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)


class Settings(BaseSettings):
    # Allow extra env vars from .env so unknown keys don't cause ValidationError (e.g. extra_forbidden)
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database URL from DATABASE_URL or DATABASE env var. Empty when unset; consumers should fall back to SQLite to avoid crash.
    database_url: str = Field(default=os.getenv("DATABASE_URL", os.getenv("DATABASE", "")), validation_alias="DATABASE_URL")

    
    # Supabase Configuration
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_service_key: str = os.getenv("SUPABASE_SERVICE_KEY", "")
    supabase_storage_bucket: str = os.getenv("SUPABASE_STORAGE_BUCKET", "slides")
    supabase_uploads_bucket: str = os.getenv("SUPABASE_UPLOADS_BUCKET", "uploads")
    
    # JWT
    jwt_secret_key: str = "your-secret-key-here-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 24
    
    # OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""
    oauth_redirect_uri: str = "http://localhost:8000/api/admin/auth/callback"
    
    # CORS: dev ports + production (Vercel, Railway). Add more via CORS_ORIGINS_EXTRA in .env (comma-separated).
    cors_origins: List[str] = [
        "http://localhost:3000",
        "http://localhost:3002",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:5176",
        "http://localhost:5177",
        "http://localhost:5178",
        "http://localhost:5179",
        "https://finaltryadmin.vercel.app",
        "https://frontend-finaltry.vercel.app",
        "https://corpaytest-admin.vercel.app",
    ]
    
    # File Storage
    upload_dir: str = "./uploads"
    max_file_size_mb: int = 50
    
    # External APIs
    share_price_api_url: str = ""
    share_price_api_key: str = ""
    powerbi_client_id: str = ""
    powerbi_client_secret: str = ""
    powerbi_tenant_id: str = ""
    powerbi_workspace_id: str = ""
    
    # Environment
    environment: str = "development"


settings = Settings()

