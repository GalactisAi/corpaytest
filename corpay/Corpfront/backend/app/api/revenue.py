from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Body
from sqlalchemy.orm import Session
from typing import Any, List, Optional
from datetime import datetime
import math
import os
from app.database import get_db
from app.models.revenue import Revenue, RevenueTrend, RevenueProportion, SharePrice
from app.models.file_upload import FileUpload, FileType
from app.models.api_config import ApiConfig
from app.schemas.revenue import RevenueResponse, RevenueTrendResponse, RevenueProportionResponse, SharePriceResponse
from app.utils.auth import get_current_admin_user
from app.utils.file_handler import save_uploaded_file, get_file_size_mb, delete_file, get_storage_public_url
from app.services.excel_parser import ExcelParser
from app.models.user import User
from pydantic import BaseModel

router = APIRouter(prefix="/api/admin/revenue", tags=["admin-revenue"])
_DEBUG_LOG_PATH = (os.getenv("APP_DEBUG_LOG_PATH") or "").strip()


def _write_debug_log(line: str) -> None:
    if not _DEBUG_LOG_PATH:
        return
    try:
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def _valid_revenue_amount(value: Any) -> Optional[float]:
    """Return a finite non-negative float for DB; None otherwise. Handles numpy/pandas nan."""
    if value is None:
        return None
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f) or f < 0:
            return None
        return f
    except (TypeError, ValueError):
        return None


def _get_config_value(db, key: str):
    row = db.query(ApiConfig).filter(ApiConfig.config_key == key, ApiConfig.is_active == 1).first()
    return (row.config_value or "").strip() or None if row else None


def _set_config_value(db, key: str, value: str) -> None:
    row = db.query(ApiConfig).filter(ApiConfig.config_key == key).first()
    if row:
        row.config_value = value or ""
    else:
        db.add(ApiConfig(config_key=key, config_value=value or "", is_active=1))
    db.commit()


@router.post("/upload")
async def upload_revenue_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Upload revenue Excel file (authenticated)"""
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="File must be Excel format (.xlsx or .xls)")
    
    # Save file
    stored_path, local_path = save_uploaded_file(file, "revenue")
    file_size = get_file_size_mb(stored_path)
    api_base = os.getenv("API_BASE_URL", "http://localhost:8080")
    storage_url = f"{api_base.rstrip('/')}/uploads/{stored_path}"
    
    # Record upload with storage_url for DB persistence
    file_upload = FileUpload(
        original_filename=file.filename,
        stored_path=stored_path,
        storage_url=storage_url,
        file_type=FileType.REVENUE,
        file_size=int(file_size * 1024 * 1024),
        uploaded_by=current_user.email
    )
    db.add(file_upload)
    
    try:
        # Parse Excel file (use local temp path when Supabase stored)
        parser = ExcelParser()
        parse_path = local_path if local_path else f"uploads/{stored_path}"
        data = parser.parse_revenue_file(parse_path)
        
        # Update revenue only when total_amount is valid (never NaN/inf) to avoid IntegrityError
        total_revenue = _valid_revenue_amount(data.get("total_revenue"))
        if total_revenue is not None:
            pct_change = data.get("percentage_change")
            try:
                pct_f = float(pct_change)
                if math.isnan(pct_f) or math.isinf(pct_f):
                    pct_f = 0.0
            except (TypeError, ValueError):
                pct_f = 0.0
            revenue = db.query(Revenue).order_by(Revenue.last_updated.desc()).first()
            if revenue:
                revenue.total_amount = total_revenue
                revenue.percentage_change = pct_f
            else:
                revenue = Revenue(
                    total_amount=total_revenue,
                    percentage_change=pct_f
                )
                db.add(revenue)
        
        # Update revenue trends
        if data.get("revenue_trends"):
            current_year = datetime.now().year
            # Clear existing trends for current year
            db.query(RevenueTrend).filter(RevenueTrend.year == current_year).delete()
            
            for trend in data["revenue_trends"]:
                revenue_trend = RevenueTrend(
                    month=trend["month"],
                    value=trend["value"],
                    highlight=trend.get("highlight", False),
                    year=current_year
                )
                db.add(revenue_trend)
        
        # Update revenue proportions
        if data.get("revenue_proportions"):
            for prop in data["revenue_proportions"]:
                proportion = db.query(RevenueProportion).filter(
                    RevenueProportion.category == prop["category"]
                ).first()
                
                if proportion:
                    proportion.percentage = prop["percentage"]
                    proportion.color = prop.get("color", "#981239")
                else:
                    proportion = RevenueProportion(
                        category=prop["category"],
                        percentage=prop["percentage"],
                        color=prop.get("color", "#981239")
                    )
                    db.add(proportion)
        
        file_upload.processed = 1
        db.commit()
        # Persist current revenue file so it survives refresh (Trend data from this file)
        _set_config_value(db, "revenue_trend_file_id", str(file_upload.id))
        _set_config_value(db, "revenue_trend_file_name", file.filename)
        _set_config_value(db, "revenue_trend_file_path", stored_path)
        return {"message": "File processed successfully", "file_id": file_upload.id}
    
    except Exception as e:
        file_upload.error_message = str(e)
        db.commit()
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")


@router.post("/upload-dev")
async def upload_revenue_file_dev(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Upload revenue Excel file (development mode - no auth required)
    
    This reuses the same processing logic as the authenticated endpoint but
    skips the admin auth dependency so it is easier to test from the Admin
    Dashboard UI.
    """
    try:
        # Debug log: entry into upload-dev
        try:
            _write_debug_log('{"sessionId":"debug-session","runId":"pre-fix","hypothesisId":"H4","location":"revenue.py:upload_revenue_file_dev:start","message":"Entered upload-dev","data":{"fileName":"%s"},"timestamp":%d}\\n' % (file.filename, int(datetime.now().timestamp() * 1000)))
        except Exception:
            pass

        if not file.filename.endswith(('.xlsx', '.xls')):
            raise HTTPException(status_code=400, detail="File must be Excel format (.xlsx or .xls)")
        
        # Save file (Supabase or local)
        stored_path, local_path = save_uploaded_file(file, "revenue")
        file_size = get_file_size_mb(stored_path)
        api_base = os.getenv("API_BASE_URL", "http://localhost:8080")
        storage_url = get_storage_public_url(stored_path, api_base)

        # Record upload with storage_url for DB persistence
        file_upload = FileUpload(
            original_filename=file.filename,
            stored_path=stored_path,
            storage_url=storage_url,
            file_type=FileType.REVENUE,
            file_size=int(file_size * 1024 * 1024),
            uploaded_by="dev_user"
        )
        db.add(file_upload)

        # Parse Excel file (use local temp path when Supabase stored)
        parser = ExcelParser()
        parse_path = local_path if local_path else f"uploads/{stored_path}"
        data = parser.parse_revenue_file(parse_path)

        # Update revenue only when total_amount is valid (never NaN/inf) to avoid IntegrityError
        total_revenue = _valid_revenue_amount(data.get("total_revenue"))
        if total_revenue is not None:
            pct_change = data.get("percentage_change")
            try:
                pct_f = float(pct_change)
                if math.isnan(pct_f) or math.isinf(pct_f):
                    pct_f = 0.0
            except (TypeError, ValueError):
                pct_f = 0.0
            revenue = db.query(Revenue).order_by(Revenue.last_updated.desc()).first()
            if revenue:
                revenue.total_amount = total_revenue
                revenue.percentage_change = pct_f
            else:
                revenue = Revenue(
                    total_amount=total_revenue,
                    percentage_change=pct_f
                )
                db.add(revenue)

        # Update revenue trends
        if data.get("revenue_trends"):
            current_year = datetime.now().year
            # Clear existing trends for current year
            db.query(RevenueTrend).filter(RevenueTrend.year == current_year).delete()

            for trend in data["revenue_trends"]:
                revenue_trend = RevenueTrend(
                    month=trend["month"],
                    value=trend["value"],
                    highlight=trend.get("highlight", False),
                    year=current_year
                )
                db.add(revenue_trend)

        # Update revenue proportions
        if data.get("revenue_proportions"):
            for prop in data["revenue_proportions"]:
                proportion = db.query(RevenueProportion).filter(
                    RevenueProportion.category == prop["category"]
                ).first()

                if proportion:
                    proportion.percentage = prop["percentage"]
                    proportion.color = prop.get("color", "#981239")
                else:
                    proportion = RevenueProportion(
                        category=prop["category"],
                        percentage=prop["percentage"],
                        color=prop.get("color", "#981239")
                    )
                    db.add(proportion)

        file_upload.processed = 1
        db.commit()
        # Persist current revenue file so it survives refresh (Trend data from this file)
        _set_config_value(db, "revenue_trend_file_id", str(file_upload.id))
        _set_config_value(db, "revenue_trend_file_name", file.filename)
        _set_config_value(db, "revenue_trend_file_path", stored_path)

        try:
            _write_debug_log('{"sessionId":"debug-session","runId":"pre-fix","hypothesisId":"H5","location":"revenue.py:upload_revenue_file_dev:success","message":"upload-dev processed successfully","data":{"fileId":%d},"timestamp":%d}\\n' % (file_upload.id, int(datetime.now().timestamp() * 1000)))
        except Exception:
            pass

        return {"message": "File processed successfully", "file_id": file_upload.id}

    except HTTPException:
        # Re-raise HTTPExceptions so FastAPI can handle status code properly
        raise
    except Exception as e:
        # Catch-all for unexpected errors
        try:
            _write_debug_log('{"sessionId":"debug-session","runId":"pre-fix","hypothesisId":"H6","location":"revenue.py:upload_revenue_file_dev:exception","message":"Unexpected exception during upload-dev","data":{"error":"%s"},"timestamp":%d}\\n' % (str(e).replace("\\", "\\\\"), int(datetime.now().timestamp() * 1000)))
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Unexpected error processing file: {str(e)}")


@router.get("/current-file-dev")
async def get_current_revenue_file_dev(db: Session = Depends(get_db)):
    """Get current revenue trend file from DB (ApiConfig or last FileUpload)."""
    file_id = _get_config_value(db, "revenue_trend_file_id")
    file_name = _get_config_value(db, "revenue_trend_file_name")
    file_path = _get_config_value(db, "revenue_trend_file_path")
    if file_id or file_name:
        return {"file_id": int(file_id) if file_id else None, "file_name": file_name or "", "file_path": file_path or ""}
    # Fallback: last uploaded revenue file from FileUpload table
    last_upload = db.query(FileUpload).filter(FileUpload.file_type == FileType.REVENUE).order_by(FileUpload.created_at.desc()).first()
    if last_upload:
        return {"file_id": last_upload.id, "file_name": last_upload.original_filename or "", "file_path": last_upload.stored_path or ""}
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail="No revenue file uploaded yet")


@router.get("/current-file")
async def get_current_revenue_file(
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Get current revenue trend file from DB (ApiConfig or last FileUpload)."""
    file_id = _get_config_value(db, "revenue_trend_file_id")
    file_name = _get_config_value(db, "revenue_trend_file_name")
    file_path = _get_config_value(db, "revenue_trend_file_path")
    if file_id or file_name:
        return {"file_id": int(file_id) if file_id else None, "file_name": file_name or "", "file_path": file_path or ""}
    last_upload = db.query(FileUpload).filter(FileUpload.file_type == FileType.REVENUE).order_by(FileUpload.created_at.desc()).first()
    if last_upload:
        return {"file_id": last_upload.id, "file_name": last_upload.original_filename or "", "file_path": last_upload.stored_path or ""}
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail="No revenue file uploaded yet")


@router.delete("/current-file-dev")
async def delete_current_revenue_file_dev(db: Session = Depends(get_db)):
    """Remove current revenue file from storage and config (dev). X button clears so new upload can replace."""
    file_path = _get_config_value(db, "revenue_trend_file_path")
    if file_path:
        delete_file(file_path)
    _set_config_value(db, "revenue_trend_file_id", "")
    _set_config_value(db, "revenue_trend_file_name", "")
    _set_config_value(db, "revenue_trend_file_path", "")
    return {"message": "Current revenue file cleared. Upload a new Excel to set trend data."}


@router.delete("/current-file")
async def delete_current_revenue_file(
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Remove current revenue file from storage and config. X button clears so new upload can replace."""
    file_path = _get_config_value(db, "revenue_trend_file_path")
    if file_path:
        delete_file(file_path)
    _set_config_value(db, "revenue_trend_file_id", "")
    _set_config_value(db, "revenue_trend_file_name", "")
    _set_config_value(db, "revenue_trend_file_path", "")
    return {"message": "Current revenue file cleared. Upload a new Excel to set trend data."}


class ManualRevenueRequest(BaseModel):
    total_amount: float
    percentage_change: float


@router.post("/manual", response_model=RevenueResponse)
async def create_manual_revenue(
    request: ManualRevenueRequest,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Manually create revenue entry"""
    revenue = Revenue(
        total_amount=request.total_amount,
        percentage_change=request.percentage_change
    )
    db.add(revenue)
    db.commit()
    db.refresh(revenue)
    return revenue


@router.post("/manual-dev", response_model=RevenueResponse)
async def create_manual_revenue_dev(
    request: ManualRevenueRequest,
    db: Session = Depends(get_db)
):
    """Manually create revenue entry (development mode - no auth required)"""
    revenue = Revenue(
        total_amount=request.total_amount,
        percentage_change=request.percentage_change
    )
    db.add(revenue)
    db.commit()
    db.refresh(revenue)
    return revenue


class ManualSharePriceRequest(BaseModel):
    price: float
    change_percentage: float


@router.post("/share-price/manual-dev", response_model=SharePriceResponse)
async def create_manual_share_price_dev(
    request: ManualSharePriceRequest,
    db: Session = Depends(get_db)
):
    """Manually create share price entry (development mode - no auth required)"""
    share_price = SharePrice(
        price=request.price,
        change_percentage=request.change_percentage,
        api_source="manual"
    )
    db.add(share_price)
    db.commit()
    db.refresh(share_price)
    return share_price


@router.post("/share-price/manual", response_model=SharePriceResponse)
async def create_manual_share_price(
    request: ManualSharePriceRequest,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Manually create share price entry"""
    share_price = SharePrice(
        price=request.price,
        change_percentage=request.change_percentage,
        api_source="manual"
    )
    db.add(share_price)
    db.commit()
    db.refresh(share_price)
    return share_price


class ProportionItem(BaseModel):
    category: str
    percentage: float
    color: str


class ManualProportionsRequest(BaseModel):
    proportions: List[ProportionItem]


@router.post("/proportions/manual-dev")
async def create_manual_proportions_dev(
    request: ManualProportionsRequest,
    db: Session = Depends(get_db)
):
    """Manually create/update revenue proportions (development mode - no auth required)"""
    # Clear existing proportions
    db.query(RevenueProportion).delete()
    
    # Add new proportions
    for prop in request.proportions:
        proportion = RevenueProportion(
            category=prop.category,
            percentage=prop.percentage,
            color=prop.color
        )
        db.add(proportion)
    
    db.commit()
    return {"message": "Proportions saved successfully", "count": len(request.proportions)}


@router.post("/proportions/manual")
async def create_manual_proportions(
    request: ManualProportionsRequest,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Manually create/update revenue proportions"""
    # Clear existing proportions
    db.query(RevenueProportion).delete()
    
    # Add new proportions
    for prop in request.proportions:
        proportion = RevenueProportion(
            category=prop.category,
            percentage=prop.percentage,
            color=prop.color
        )
        db.add(proportion)
    
    db.commit()
    return {"message": "Proportions saved successfully", "count": len(request.proportions)}

