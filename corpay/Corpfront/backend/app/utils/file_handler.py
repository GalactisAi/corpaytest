import shutil
import uuid
from pathlib import Path
from typing import Optional, Tuple

import httpx
from fastapi import UploadFile

from app.config import settings


def ensure_upload_dir():
    """Ensure local upload directory exists (used when Supabase is not configured)."""
    upload_path = Path(settings.upload_dir)
    upload_path.mkdir(parents=True, exist_ok=True)
    return upload_path


def _upload_to_supabase_bytes(
    content: bytes, filename: str, content_type: Optional[str], subdirectory: str
) -> Tuple[str, str]:
    """Upload bytes to Supabase Storage. Returns (relative_path, public_url)."""
    bucket = (settings.supabase_uploads_bucket or "uploads").strip() or "uploads"
    base = (settings.supabase_url or "").strip().rstrip("/")
    key = (settings.supabase_service_key or "").strip()
    if not base or not key:
        raise ValueError("Supabase URL and service key required for storage upload")

    ext = Path(filename or "").suffix or ""
    name = f"{uuid.uuid4()}{ext}"
    object_path = f"{subdirectory}/{name}" if subdirectory else name
    upload_url = f"{base}/storage/v1/object/{bucket}/{object_path}"
    public_url = f"{base}/storage/v1/object/public/{bucket}/{object_path}"

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": content_type or "application/octet-stream",
    }
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(upload_url, content=content, headers=headers)
        resp.raise_for_status()
    return object_path, public_url


def save_uploaded_file(
    file: UploadFile, subdirectory: str = ""
) -> Tuple[str, Optional[str]]:
    """
    Save uploaded file to Supabase Storage when configured, else to local ./uploads.
    Returns (stored_path, local_path_for_parsing). stored_path is the path to store in DB.
    local_path_for_parsing is set when using Supabase (temp file for Excel/etc parsers); else None (use uploads/stored_path).
    """
    subdir = subdirectory or "uploads"
    if (settings.supabase_url or "").strip() and (settings.supabase_service_key or "").strip():
        content = file.file.read()
        file.file.seek(0)
        path, _ = _upload_to_supabase_bytes(content, file.filename or "", file.content_type, subdir)
        # Write to temp so callers can parse (Excel etc.) then remove
        import tempfile
        upload_dir = ensure_upload_dir()
        tmp_dir = upload_dir / "_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        ext = Path(file.filename or "").suffix or ""
        tmp_path = tmp_dir / f"{uuid.uuid4()}{ext}"
        tmp_path.write_bytes(content)
        return path, str(tmp_path)
    # Local fallback
    upload_dir = ensure_upload_dir()
    if subdirectory:
        target_dir = upload_dir / subdirectory
        target_dir.mkdir(parents=True, exist_ok=True)
    else:
        target_dir = upload_dir
    file_extension = Path(file.filename or "").suffix or ""
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    file_path = target_dir / unique_filename
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return str(file_path.relative_to(upload_dir)), None


def save_uploaded_file_local(
    file: UploadFile, subdirectory: str = ""
) -> Tuple[str, Optional[str]]:
    """
    Force-save uploaded file to local ./uploads (bypasses Supabase). Returns (stored_path, None).
    Useful as a fallback when Supabase upload fails or is misconfigured.
    """
    subdir = subdirectory or "uploads"
    upload_dir = ensure_upload_dir()
    if subdirectory:
        target_dir = upload_dir / subdirectory
        target_dir.mkdir(parents=True, exist_ok=True)
    else:
        target_dir = upload_dir
    file_extension = Path(file.filename or "").suffix or ""
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    file_path = target_dir / unique_filename
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return str(file_path.relative_to(upload_dir)), None


def get_storage_public_url(relative_path: str, api_base: str = "") -> str:
    if relative_path.startswith("http://") or relative_path.startswith("https://"):
        return relative_path

    # If Supabase is configured, always use Supabase URL
    supabase_base = (settings.supabase_url or "").strip().rstrip("/")
    if supabase_base:
        bucket = (settings.supabase_uploads_bucket or "uploads").strip() or "uploads"
        return f"{supabase_base}/storage/v1/object/public/{bucket}/{relative_path}"

    # Local fallback only when Supabase not configured
    try:
        upload_dir = Path(settings.upload_dir)
        full_path = upload_dir / relative_path
        if full_path.exists():
            base = (api_base or "").rstrip("/")
            return f"{base}/uploads/{relative_path.lstrip('/')}" if base else f"/uploads/{relative_path.lstrip('/')}"
    except Exception:
        pass

    base = (api_base or "").rstrip("/")
    return f"{base}/uploads/{relative_path.lstrip('/')}" if base else f"/uploads/{relative_path.lstrip('/')}"


def delete_file(file_path: str) -> bool:
    """Delete a file from local upload directory. No-op for Supabase (object can be removed via Supabase API if needed)."""
    if (settings.supabase_url or "").strip() and (settings.supabase_service_key or "").strip():
        # Optional: call Supabase Storage delete API. For now we only delete from DB; object remains in bucket.
        return True
    try:
        upload_dir = Path(settings.upload_dir)
        full_path = upload_dir / file_path
        if full_path.exists():
            full_path.unlink()
            return True
        return False
    except Exception:
        return False


def get_file_size_mb(file_path: str) -> float:
    """Get file size in MB from local disk. For Supabase-stored files returns 0 if not present locally."""
    try:
        upload_dir = Path(settings.upload_dir)
        full_path = upload_dir / file_path
        if full_path.exists():
            return full_path.stat().st_size / (1024 * 1024)
    except Exception:
        pass
    return 0.0


def get_local_path(file_path: str) -> Optional[Path]:
    """Return local Path for a stored file if it exists on disk; None for Supabase-only or missing."""
    upload_dir = Path(settings.upload_dir)
    full_path = upload_dir / file_path
    return full_path if full_path.exists() else None


def get_local_path_or_download(stored_path: str) -> str:
    """
    Return a local filesystem path for reading the file. When using Supabase, downloads to temp and returns that path.
    Caller can read the file from the returned path. Temp files are not auto-deleted.
    """
    if not (settings.supabase_url or "").strip() or not (settings.supabase_service_key or "").strip():
        upload_dir = Path(settings.upload_dir)
        return str(upload_dir / stored_path)
    base = (settings.supabase_url or "").strip().rstrip("/")
    bucket = (settings.supabase_uploads_bucket or "uploads").strip() or "uploads"
    key = (settings.supabase_service_key or "").strip()
    url = f"{base}/storage/v1/object/public/{bucket}/{stored_path}"
    import tempfile
    with httpx.Client(timeout=60.0) as client:
        r = client.get(url)
        r.raise_for_status()
    tmp = Path(tempfile.gettempdir()) / f"supabase_{uuid.uuid4()}_{Path(stored_path).name}"
    tmp.write_bytes(r.content)
    return str(tmp)
