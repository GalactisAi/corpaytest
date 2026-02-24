from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Body
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from typing import Optional, List, Literal
from datetime import datetime
import time
from urllib.parse import urlparse
from app.database import get_db
from app.utils.auth import get_current_admin_user
from app.utils.file_handler import save_uploaded_file, get_file_size_mb, delete_file, get_storage_public_url, get_local_path_or_download
from app.models.user import User
from app.models.file_upload import FileUpload, FileType
from app.models.api_config import ApiConfig
from pydantic import BaseModel
import json
import os
from pathlib import Path
from app.config import settings
import subprocess
import shutil
import sys
import re
import tempfile
from pptx import Presentation
from io import BytesIO
from PIL import Image
import io
import httpx

router = APIRouter(prefix="/api", tags=["slideshow"])


def _find_libreoffice() -> str:
    """Find LibreOffice (soffice) executable on Windows, macOS, or Linux."""
    if sys.platform == "win32":
        candidates = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            "soffice",
            "libreoffice",
        ]
    elif sys.platform == "darwin":
        candidates = [
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
            "soffice",
            "libreoffice",
        ]
    else:
        candidates = [
            "/usr/bin/soffice",
            "/usr/bin/libreoffice",
            "soffice",
            "libreoffice",
        ]

    for path in candidates:
        try:
            if os.sep in path and not os.path.exists(path):
                continue
            result = subprocess.run(
                [path, "--version"],
                capture_output=True,
                timeout=10,
                text=True,
                cwd=os.path.expanduser("~"),
            )
            out = (result.stdout or "") + (result.stderr or "")
            if result.returncode == 0 or "LibreOffice" in out:
                return path
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            continue
    raise FileNotFoundError(
        "LibreOffice not found. Install it: "
        "Windows: https://www.libreoffice.org/download/download/ | "
        "macOS: brew install --cask libreoffice | "
        "Linux: sudo apt install libreoffice (or equivalent)."
    )


class SlideshowState(BaseModel):
    is_active: bool
    type: Literal["file", "url"] = "file"
    source: Optional[str] = None
    file_url: Optional[str] = None
    file_name: Optional[str] = None
    started_at: Optional[datetime] = None
    interval_seconds: Optional[int] = 5


class SlideshowStartBody(BaseModel):
    interval_seconds: Optional[int] = 5


class SlideshowSetUrlBody(BaseModel):
    embed_url: str


def _is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


# In-memory runtime state (is_active, started_at); file/url persisted in ApiConfig
_slideshow_state = {
    "is_active": False,
    "type": "file",
    "source": None,
    "file_url": None,
    "file_name": None,
    "started_at": None,
    "interval_seconds": 5
}

SLIDESHOW_KEYS = ("slideshow_file_url", "slideshow_file_name", "slideshow_type", "slideshow_embed_url")

# In-memory cache for slideshow config to avoid hammering DB on every poll (30s TTL)
_config_cache: dict[str, Optional[str]] = {}
_config_cache_time: dict[str, float] = {}
_CONFIG_CACHE_TTL = 30


def _clear_config_cache(keys: Optional[list[str]] = None) -> None:
    """Clear cached config values so subsequent reads reflect DB updates immediately."""
    targets = set(keys or [])
    for k in list(_config_cache.keys()):
        if not targets or k in targets:
            _config_cache.pop(k, None)
            _config_cache_time.pop(k, None)


def _get_config_value(db: Session, key: str) -> Optional[str]:
    now = time.time()
    if key in _config_cache and key in _config_cache_time and (now - _config_cache_time[key]) < _CONFIG_CACHE_TTL:
        return _config_cache[key]
    try:
        row = db.query(ApiConfig).filter(ApiConfig.config_key == key, ApiConfig.is_active == 1).first()
        value = (row.config_value or "").strip() or None if row else None
        _config_cache[key] = value
        _config_cache_time[key] = now
        return value
    except OperationalError:
        return None


def _set_config_value(db: Session, key: str, value: Optional[str]) -> None:
    _config_cache[key] = value or None
    _config_cache_time[key] = time.time()
    row = db.query(ApiConfig).filter(ApiConfig.config_key == key).first()
    if row:
        row.config_value = value or ""
    else:
        db.add(ApiConfig(config_key=key, config_value=value or "", is_active=1))
    db.commit()


def _load_slideshow_file_from_db(db: Session) -> None:
    """Load persisted slideshow file/url from ApiConfig or last FileUpload into _slideshow_state."""
    url = _get_config_value(db, "slideshow_file_url")
    name = _get_config_value(db, "slideshow_file_name")
    typ = _get_config_value(db, "slideshow_type") or "file"
    embed = _get_config_value(db, "slideshow_embed_url")
    if url and name:
        _slideshow_state["type"] = "file"
        _slideshow_state["source"] = url
        _slideshow_state["file_url"] = url
        _slideshow_state["file_name"] = name
    elif typ == "url" and embed:
        _slideshow_state["type"] = "url"
        _slideshow_state["source"] = embed
        _slideshow_state["file_url"] = None
        _slideshow_state["file_name"] = None
    else:
        # Fallback: last slideshow file from FileUpload table
        last_upload = db.query(FileUpload).filter(FileUpload.file_type == FileType.SLIDESHOW).order_by(FileUpload.created_at.desc()).first()
        if last_upload and (last_upload.storage_url or last_upload.stored_path):
            file_url = last_upload.storage_url or get_storage_public_url(last_upload.stored_path, os.getenv("API_BASE_URL", "http://localhost:8080"))
            _slideshow_state["type"] = "file"
            _slideshow_state["source"] = file_url
            _slideshow_state["file_url"] = file_url
            _slideshow_state["file_name"] = last_upload.original_filename or "slideshow"
            _slideshow_state["stored_path"] = last_upload.stored_path


@router.post("/admin/slideshow/upload-dev")
async def upload_ppt_file_dev(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Upload PowerPoint or PDF file for slideshow (development mode - no auth required)"""
    # Replace any previous slideshow file
    _delete_slideshow_file_and_state(db)
    if not file.filename or not file.filename.lower().endswith(('.pptx', '.ppt', '.pdf')):
        raise HTTPException(status_code=400, detail="File must be PowerPoint (.pptx, .ppt) or PDF (.pdf)")
    
    # Save file (Supabase or local)
    stored_path, _ = save_uploaded_file(file, "slideshow")
    file_size = get_file_size_mb(stored_path)
    API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8080")
    file_url = get_storage_public_url(stored_path, API_BASE_URL)
    
    # Record upload with storage_url for DB persistence
    try:
        file_upload = FileUpload(
            original_filename=file.filename,
            stored_path=stored_path,
            storage_url=file_url,
            file_type=FileType.SLIDESHOW,
            file_size=int(file_size * 1024 * 1024),
            uploaded_by="dev_user"
        )
        db.add(file_upload)
        db.commit()
    except Exception as e:
        print(f"Warning: Could not record file upload: {e}")
    
    # Update slideshow state with file info (but don't activate yet)
    _slideshow_state["type"] = "file"
    _slideshow_state["source"] = file_url
    _slideshow_state["file_url"] = file_url
    _slideshow_state["file_name"] = file.filename
    _slideshow_state["stored_path"] = stored_path
    # Persist to DB so it survives refresh/restart
    _set_config_value(db, "slideshow_file_url", file_url)
    _set_config_value(db, "slideshow_file_name", file.filename)
    _set_config_value(db, "slideshow_type", "file")
    _set_config_value(db, "slideshow_embed_url", "")
    _clear_config_cache(list(SLIDESHOW_KEYS))
    
    return {
        "message": "File uploaded successfully",
        "file_url": file_url,
        "file_name": file.filename,
        "file_path": stored_path
    }


@router.post("/admin/slideshow/upload")
async def upload_ppt_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Upload PowerPoint or PDF file for slideshow"""
    # Replace any previous slideshow file
    _delete_slideshow_file_and_state(db)
    if not file.filename or not file.filename.lower().endswith(('.pptx', '.ppt', '.pdf')):
        raise HTTPException(status_code=400, detail="File must be PowerPoint (.pptx, .ppt) or PDF (.pdf)")
    
    # Save file (Supabase or local)
    stored_path, _ = save_uploaded_file(file, "slideshow")
    file_size = get_file_size_mb(stored_path)
    API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8080")
    file_url = get_storage_public_url(stored_path, API_BASE_URL)
    
    # Record upload with storage_url for DB persistence
    try:
        file_upload = FileUpload(
            original_filename=file.filename,
            stored_path=stored_path,
            storage_url=file_url,
            file_type=FileType.SLIDESHOW,
            file_size=int(file_size * 1024 * 1024),
            uploaded_by=current_user.email
        )
        db.add(file_upload)
        db.commit()
    except Exception as e:
        print(f"Warning: Could not record file upload: {e}")
    
    # Update slideshow state with file info (but don't activate yet)
    _slideshow_state["type"] = "file"
    _slideshow_state["source"] = file_url
    _slideshow_state["file_url"] = file_url
    _slideshow_state["file_name"] = file.filename
    _slideshow_state["stored_path"] = stored_path
    # Persist to DB so it survives refresh/restart
    _set_config_value(db, "slideshow_file_url", file_url)
    _set_config_value(db, "slideshow_file_name", file.filename)
    _set_config_value(db, "slideshow_type", "file")
    _set_config_value(db, "slideshow_embed_url", "")
    _clear_config_cache(list(SLIDESHOW_KEYS))
    
    return {
        "message": "File uploaded successfully",
        "file_url": file_url,
        "file_name": file.filename,
        "file_path": stored_path
    }


@router.post("/admin/slideshow/set-url-dev")
async def set_slideshow_url_dev(
    body: SlideshowSetUrlBody,
    db: Session = Depends(get_db)
):
    """Set Power BI (or other) embed URL for slideshow (development mode - no auth required)"""
    url = (body.embed_url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="embed_url is required")
    if not _is_valid_url(url):
        raise HTTPException(status_code=400, detail="Invalid URL. Must be a valid http or https URL.")
    _slideshow_state["type"] = "url"
    _slideshow_state["source"] = url
    _slideshow_state["file_url"] = None
    _slideshow_state["file_name"] = None
    _slideshow_state["stored_path"] = None
    _set_config_value(db, "slideshow_file_url", "")
    _set_config_value(db, "slideshow_file_name", "")
    _set_config_value(db, "slideshow_type", "url")
    _set_config_value(db, "slideshow_embed_url", url)
    _clear_config_cache(list(SLIDESHOW_KEYS))
    return {
        "message": "Embed URL set successfully",
        "source": url,
        "type": "url"
    }


@router.post("/admin/slideshow/set-url")
async def set_slideshow_url(
    body: SlideshowSetUrlBody,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Set Power BI (or other) embed URL for slideshow"""
    url = (body.embed_url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="embed_url is required")
    if not _is_valid_url(url):
        raise HTTPException(status_code=400, detail="Invalid URL. Must be a valid http or https URL.")
    _slideshow_state["type"] = "url"
    _slideshow_state["source"] = url
    _slideshow_state["file_url"] = None
    _slideshow_state["file_name"] = None
    _slideshow_state["stored_path"] = None
    _set_config_value(db, "slideshow_file_url", "")
    _set_config_value(db, "slideshow_file_name", "")
    _set_config_value(db, "slideshow_type", "url")
    _set_config_value(db, "slideshow_embed_url", url)
    _clear_config_cache(list(SLIDESHOW_KEYS))
    return {
        "message": "Embed URL set successfully",
        "source": url,
        "type": "url"
    }


@router.post("/admin/slideshow/start-dev")
async def start_slideshow_dev(
    body: Optional[SlideshowStartBody] = Body(default=None),
    db: Session = Depends(get_db)
):
    """Start the slideshow on frontend dashboard (development mode - no auth required)"""
    _load_slideshow_file_from_db(db)
    source = _slideshow_state.get("source") or _slideshow_state.get("file_url")
    if not source:
        raise HTTPException(status_code=400, detail="No presentation set. Please upload a file or set an embed URL first.")
    
    if body and body.interval_seconds is not None:
        _slideshow_state["interval_seconds"] = max(1, min(300, body.interval_seconds))  # clamp 1–300
    _slideshow_state["is_active"] = True
    _slideshow_state["started_at"] = datetime.now()
    
    return {
        "message": "Slideshow started",
        "is_active": True,
        "type": _slideshow_state.get("type", "file"),
        "source": source,
        "file_url": _slideshow_state["file_url"],
        "file_name": _slideshow_state["file_name"],
        "interval_seconds": _slideshow_state["interval_seconds"]
    }


@router.post("/admin/slideshow/start")
async def start_slideshow(
    body: Optional[SlideshowStartBody] = Body(default=None),
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Start the slideshow on frontend dashboard"""
    _load_slideshow_file_from_db(db)
    source = _slideshow_state.get("source") or _slideshow_state.get("file_url")
    if not source:
        raise HTTPException(status_code=400, detail="No presentation set. Please upload a file or set an embed URL first.")
    
    if body and body.interval_seconds is not None:
        _slideshow_state["interval_seconds"] = max(1, min(300, body.interval_seconds))
    _slideshow_state["is_active"] = True
    _slideshow_state["started_at"] = datetime.now()
    
    return {
        "message": "Slideshow started",
        "is_active": True,
        "type": _slideshow_state.get("type", "file"),
        "source": source,
        "file_url": _slideshow_state["file_url"],
        "file_name": _slideshow_state["file_name"],
        "interval_seconds": _slideshow_state["interval_seconds"]
    }


@router.post("/admin/slideshow/stop-dev")
async def stop_slideshow_dev(
    db: Session = Depends(get_db)
):
    """Stop the slideshow on frontend dashboard (development mode - no auth required)"""
    _slideshow_state["is_active"] = False
    _slideshow_state["started_at"] = None
    
    return {
        "message": "Slideshow stopped",
        "is_active": False
    }


@router.post("/admin/slideshow/stop")
async def stop_slideshow(
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Stop the slideshow on frontend dashboard"""
    _slideshow_state["is_active"] = False
    _slideshow_state["started_at"] = None
    
    return {
        "message": "Slideshow stopped",
        "is_active": False
    }


def _slideshow_file_url_to_relative_path(file_url: str) -> Optional[str]:
    """Extract relative path under uploads/ from stored file URL."""
    if not file_url or "/uploads/" not in file_url:
        return None
    path = file_url.split("/uploads/", 1)[1].strip().lstrip("/")
    return path.replace("\\", "/") if path else None


def _delete_slideshow_file_and_state(db: Session) -> None:
    """Remove current slideshow file from disk and DB (config + FileUpload fallback). Idempotent."""
    file_url = _get_config_value(db, "slideshow_file_url")
    rel_path = _slideshow_file_url_to_relative_path(file_url or "")
    if rel_path:
        delete_file(rel_path)
    else:
        # File may have been loaded from FileUpload fallback; remove that record and file
        last_upload = db.query(FileUpload).filter(FileUpload.file_type == FileType.SLIDESHOW).order_by(FileUpload.created_at.desc()).first()
        if last_upload:
            if last_upload.stored_path:
                delete_file(last_upload.stored_path)
            db.delete(last_upload)
            db.commit()
    _slideshow_state["type"] = "file"
    _slideshow_state["source"] = None
    _slideshow_state["file_url"] = None
    _slideshow_state["file_name"] = None
    _slideshow_state["stored_path"] = None
    for key in SLIDESHOW_KEYS:
        _set_config_value(db, key, "")
    _clear_config_cache(list(SLIDESHOW_KEYS))
    return None


@router.delete("/admin/slideshow/file-dev")
async def delete_slideshow_file_dev(db: Session = Depends(get_db)):
    """Remove persisted slideshow file (dev, no auth). Deletes from storage and DB. Call X button. Always returns 200."""
    _delete_slideshow_file_and_state(db)
    return {"message": "Slideshow file removed. Upload a new file to replace."}


@router.delete("/admin/slideshow/file")
async def delete_slideshow_file(
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Remove persisted slideshow file. Deletes from storage and DB. Call X button. Always returns 200."""
    _delete_slideshow_file_and_state(db)
    return {"message": "Slideshow file removed. Upload a new file to replace."}


@router.get("/dashboard/slideshow", response_model=SlideshowState)
async def get_slideshow_state(db: Session = Depends(get_db)):
    """Get current slideshow state (public endpoint for frontend dashboard). Loads persisted file/url from DB."""
    _load_slideshow_file_from_db(db)
    slideshow_type = _slideshow_state.get("type", "file")
    source = _slideshow_state.get("source") or _slideshow_state.get("file_url")
    return SlideshowState(
        is_active=_slideshow_state["is_active"],
        type=slideshow_type,
        source=source,
        file_url=_slideshow_state["file_url"],
        file_name=_slideshow_state["file_name"],
        started_at=_slideshow_state["started_at"],
        interval_seconds=_slideshow_state.get("interval_seconds", 5)
    )


@router.get("/dashboard/slideshow/slides")
async def get_slide_images(db: Session = Depends(get_db)):
    """Convert PPT/PPTX or PDF to slide images for display. Loads persisted file from DB if needed."""
    _load_slideshow_file_from_db(db)
    if not _slideshow_state["file_url"]:
        raise HTTPException(status_code=404, detail="No presentation file uploaded")
    
    upload_dir = Path(settings.upload_dir)
    # Resolve local path: use stored_path from DB (works with Supabase or local) or fallback to URL-derived path
    stored_path = _slideshow_state.get("stored_path")
    if stored_path:
        full_file_path = Path(get_local_path_or_download(stored_path))
    else:
        file_url_raw = _slideshow_state["file_url"] or ""
        if "/uploads/" in file_url_raw:
            file_path = file_url_raw.split("/uploads/", 1)[1].lstrip("/")
        else:
            file_path = file_url_raw.replace("http://localhost:8000/uploads/", "").replace("http://localhost:8080/uploads/", "").lstrip("/")
        full_file_path = upload_dir / file_path
    if not full_file_path.exists():
        raise HTTPException(status_code=404, detail="Presentation file not found")
    
    slides_dir = upload_dir / "slideshow" / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)
    
    base_name = full_file_path.stem
    API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8080")
    suffix = full_file_path.suffix.lower()

    # PDF: convert each page to PNG with PyMuPDF (no LibreOffice needed)
    if suffix == ".pdf":
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise HTTPException(
                status_code=500,
                detail="PDF support requires the pymupdf package. Install with: pip install pymupdf",
            )
        try:
            # Cache: return existing slide URLs if same file (path + mtime) was already converted
            meta_path = slides_dir / f"{base_name}.pdf.meta"
            file_path_key = str(full_file_path.resolve())
            file_mtime = str(full_file_path.stat().st_mtime)
            supabase_base = (settings.supabase_url or "").strip().rstrip("/")
            supabase_key = (settings.supabase_service_key or "").strip()
            bucket = (settings.supabase_uploads_bucket or "uploads").strip() or "uploads"
            use_supabase = bool(supabase_base and supabase_key)

            if meta_path.exists():
                try:
                    with open(meta_path, "r") as f:
                        meta_lines = [line.strip() for line in f.read().splitlines()]
                    if len(meta_lines) >= 2 and meta_lines[0] == file_path_key and meta_lines[1] == file_mtime:
                        cached_urls = [line for line in meta_lines[2:] if line]
                        if cached_urls:
                            print(f"[Slideshow] PDF serving {len(cached_urls)} cached slides")
                            return {"slides": cached_urls, "use_viewer": False}
                except (ValueError, OSError):
                    pass

            for old in slides_dir.glob(f"{base_name}*.png"):
                try:
                    old.unlink()
                except OSError:
                    pass
            for old in slides_dir.glob(f"{base_name}.pdf.meta"):
                try:
                    old.unlink()
                except OSError:
                    pass

            # 1.5x scale for faster conversion (was 2.0)
            PDF_SCALE = 1.5
            doc = fitz.open(str(full_file_path))
            slide_images = []

            if use_supabase:
                with httpx.Client(timeout=60.0) as client:
                    for i in range(len(doc)):
                        page = doc[i]
                        mat = fitz.Matrix(PDF_SCALE, PDF_SCALE)
                        pix = page.get_pixmap(matrix=mat, alpha=False)
                        slide_name = f"{base_name}_{i + 1}.png"
                        object_path = f"slideshow/slides/{slide_name}"
                        upload_url = f"{supabase_base}/storage/v1/object/{bucket}/{object_path}"
                        headers = {
                            "Authorization": f"Bearer {supabase_key}",
                            "Content-Type": "image/png",
                            "x-upsert": "true",
                        }
                        resp = client.post(upload_url, content=pix.tobytes("png"), headers=headers)
                        resp.raise_for_status()
                        slide_images.append(
                            f"{supabase_base}/storage/v1/object/public/{bucket}/{object_path}"
                        )
            else:
                for i in range(len(doc)):
                    page = doc[i]
                    mat = fitz.Matrix(PDF_SCALE, PDF_SCALE)
                    pix = page.get_pixmap(matrix=mat, alpha=False)
                    out_path = slides_dir / f"{base_name}_{i + 1}.png"
                    pix.save(str(out_path))
                    slide_images.append(f"{API_BASE_URL}/uploads/slideshow/slides/{out_path.name}")

            doc.close()
            if slide_images:
                with open(meta_path, "w") as f:
                    f.write(file_path_key + "\n")
                    f.write(file_mtime + "\n")
                    f.write("\n".join(slide_images))
                print(f"[Slideshow] PDF converted to {len(slide_images)} slides")
                return {"slides": slide_images, "use_viewer": False}
            raise HTTPException(status_code=500, detail="PDF has no pages")
        except fitz.FileDataError as e:
            raise HTTPException(status_code=400, detail=f"Invalid or corrupted PDF: {e}")
        except Exception as e:
            print(f"[Slideshow] PDF conversion error: {e}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Failed to convert PDF to images: {e}")

    # PPT/PPTX: disabled on cloud (Railway has no LibreOffice)
    raise HTTPException(
        status_code=400,
        detail="PPT/PPTX upload is disabled on cloud deployment. Please upload PDF format.",
    )
