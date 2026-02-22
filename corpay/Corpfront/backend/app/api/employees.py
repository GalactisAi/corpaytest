from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models.employees import EmployeeMilestone
from app.models.file_upload import FileUpload, FileType
from app.schemas.employees import EmployeeMilestoneCreate, EmployeeMilestoneUpdate, EmployeeMilestoneResponse
from app.utils.auth import get_current_admin_user
from app.utils.file_handler import (
    save_uploaded_file,
    save_uploaded_file_local,
    get_file_size_mb,
    get_storage_public_url,
    delete_file,
)
from app.services.excel_parser import ExcelParser
from app.models.user import User
import os

router = APIRouter(prefix="/api/admin/employees", tags=["admin-employees"])
_API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8080")


def _public_avatar_url(path: str) -> str:
    """Return absolute URL for stored avatar path (Supabase or local uploads)."""
    if not path:
        return path
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return get_storage_public_url(path, _API_BASE_URL)


@router.post("/dev", response_model=EmployeeMilestoneResponse)
async def create_employee_milestone_dev(
    milestone: EmployeeMilestoneCreate,
    db: Session = Depends(get_db)
):
    """Create a new employee milestone (development mode - no auth required)"""
    db_milestone = EmployeeMilestone(**milestone.dict())
    db.add(db_milestone)
    db.commit()
    db.refresh(db_milestone)
    db_milestone.avatar_path = _public_avatar_url(db_milestone.avatar_path)
    return db_milestone


@router.post("", response_model=EmployeeMilestoneResponse)
async def create_employee_milestone(
    milestone: EmployeeMilestoneCreate,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Create a new employee milestone"""
    db_milestone = EmployeeMilestone(**milestone.dict())
    db.add(db_milestone)
    db.commit()
    db.refresh(db_milestone)
    db_milestone.avatar_path = _public_avatar_url(db_milestone.avatar_path)
    return db_milestone


@router.put("/dev/{milestone_id}", response_model=EmployeeMilestoneResponse)
@router.patch("/dev/{milestone_id}", response_model=EmployeeMilestoneResponse)
async def update_employee_milestone_dev(
    milestone_id: int,
    milestone: EmployeeMilestoneUpdate,
    db: Session = Depends(get_db)
):
    """Update an employee milestone (development mode - no auth required)"""
    db_milestone = db.query(EmployeeMilestone).filter(EmployeeMilestone.id == milestone_id).first()
    if not db_milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")
    for key, value in milestone.dict().items():
        setattr(db_milestone, key, value)
    db.commit()
    db.refresh(db_milestone)
    db_milestone.avatar_path = _public_avatar_url(db_milestone.avatar_path)
    return db_milestone


@router.put("/{milestone_id}", response_model=EmployeeMilestoneResponse)
@router.patch("/{milestone_id}", response_model=EmployeeMilestoneResponse)
async def update_employee_milestone(
    milestone_id: int,
    milestone: EmployeeMilestoneUpdate,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Update an employee milestone"""
    db_milestone = db.query(EmployeeMilestone).filter(EmployeeMilestone.id == milestone_id).first()
    if not db_milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")
    for key, value in milestone.dict().items():
        setattr(db_milestone, key, value)
    db.commit()
    db.refresh(db_milestone)
    db_milestone.avatar_path = _public_avatar_url(db_milestone.avatar_path)
    return db_milestone


@router.get("/dev", response_model=List[EmployeeMilestoneResponse])
async def list_employee_milestones_dev(
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """List all employee milestones (development mode - no auth required)"""
    milestones = db.query(EmployeeMilestone).filter(
        EmployeeMilestone.is_active == 1
    ).order_by(EmployeeMilestone.milestone_date.desc()).limit(limit).all()
    for m in milestones:
        m.avatar_path = _public_avatar_url(m.avatar_path)
    return milestones


@router.get("", response_model=List[EmployeeMilestoneResponse])
async def list_employee_milestones(
    limit: int = 50,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """List all employee milestones"""
    milestones = db.query(EmployeeMilestone).filter(
        EmployeeMilestone.is_active == 1
    ).order_by(EmployeeMilestone.milestone_date.desc()).limit(limit).all()
    for m in milestones:
        m.avatar_path = _public_avatar_url(m.avatar_path)
    return milestones


@router.post("/upload")
async def upload_employee_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Upload employee data Excel file"""
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="File must be Excel format")
    
    stored_path, local_path = save_uploaded_file(file, "employees")
    file_size = get_file_size_mb(stored_path)
    
    file_upload = FileUpload(
        original_filename=file.filename,
        stored_path=stored_path,
        file_type=FileType.EMPLOYEE_DATA,
        file_size=int(file_size * 1024 * 1024),
        uploaded_by=current_user.email
    )
    db.add(file_upload)
    
    try:
        parser = ExcelParser()
        parse_path = local_path if local_path else f"uploads/{stored_path}"
        employees = parser.parse_employee_file(parse_path)
        
        for emp_data in employees:
            milestone = EmployeeMilestone(**emp_data)
            db.add(milestone)
        
        file_upload.processed = 1
        db.commit()
        
        return {"message": f"Processed {len(employees)} employee milestones", "file_id": file_upload.id}
    
    except Exception as e:
        file_upload.error_message = str(e)
        db.commit()
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")


@router.post("/upload-photo-dev")
async def upload_employee_photo_dev(
    file: UploadFile = File(...),
    employee_id: int = Form(0),
    db: Session = Depends(get_db)
):
    """Upload employee photo (development mode - no auth required)"""
    if not file.content_type or not file.content_type.startswith('image/'):
        raise HTTPException(status_code=400, detail="File must be an image")
    if not file.filename:
        raise HTTPException(status_code=400, detail="File must have a filename")

    try:
        try:
            stored_path, _ = save_uploaded_file(file, "employee-photos")
        except Exception:
            # Fallback to local storage if Supabase upload fails or is misconfigured
            file.file.seek(0)
            stored_path, _ = save_uploaded_file_local(file, "employee-photos")
        file_size = get_file_size_mb(stored_path)
        storage_url = get_storage_public_url(stored_path, _API_BASE_URL)

        file_upload = FileUpload(
            original_filename=file.filename,
            stored_path=stored_path,
            storage_url=storage_url,
            file_type=FileType.EMPLOYEE_PHOTO,
            file_size=int(file_size * 1024 * 1024) if file_size > 0 else None,
            uploaded_by="dev_user",
            processed=1,
        )
        db.add(file_upload)

        if employee_id > 0:
            milestone = db.query(EmployeeMilestone).filter(EmployeeMilestone.id == employee_id).first()
            if milestone:
                # Store the public URL so clients don't need to resolve stored_path
                milestone.avatar_path = storage_url or stored_path

        db.commit()
        return {"message": "Photo uploaded successfully", "avatar_path": storage_url, "stored_path": stored_path}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error uploading photo: {str(e)}")


@router.post("/upload-photo")
async def upload_employee_photo(
    file: UploadFile = File(...),
    employee_id: int = Form(0),
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Upload employee photo (Supabase Storage or local)"""
    if not file.content_type or not file.content_type.startswith('image/'):
        raise HTTPException(status_code=400, detail="File must be an image")
    if not file.filename:
        raise HTTPException(status_code=400, detail="File must have a filename")

    try:
        try:
            stored_path, _ = save_uploaded_file(file, "employee-photos")
        except Exception:
            file.file.seek(0)
            stored_path, _ = save_uploaded_file_local(file, "employee-photos")
        file_size = get_file_size_mb(stored_path)
        storage_url = get_storage_public_url(stored_path, _API_BASE_URL)

        file_upload = FileUpload(
            original_filename=file.filename,
            stored_path=stored_path,
            storage_url=storage_url,
            file_type=FileType.EMPLOYEE_PHOTO,
            file_size=int(file_size * 1024 * 1024) if file_size > 0 else None,
            uploaded_by=current_user.email,
            processed=1,
        )
        db.add(file_upload)

        if employee_id > 0:
            milestone = db.query(EmployeeMilestone).filter(EmployeeMilestone.id == employee_id).first()
            if not milestone:
                raise HTTPException(status_code=404, detail="Employee milestone not found")
            # Store the public URL so clients don't need to resolve stored_path
            milestone.avatar_path = storage_url or stored_path

        db.commit()
        return {"message": "Photo uploaded successfully", "avatar_path": storage_url, "stored_path": stored_path}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error uploading photo: {str(e)}")


@router.delete("/dev/{milestone_id}")
async def delete_milestone_dev(
    milestone_id: int,
    db: Session = Depends(get_db)
):
    """Delete an employee milestone (development mode - no auth required)"""
    milestone = db.query(EmployeeMilestone).filter(EmployeeMilestone.id == milestone_id).first()
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")

    avatar = milestone.avatar_path or ""
    db.delete(milestone)
    db.commit()
    if avatar:
        delete_file(avatar)
    return {"message": "Milestone deleted successfully"}


@router.delete("/{milestone_id}")
async def delete_milestone(
    milestone_id: int,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Delete an employee milestone (hard delete)"""
    milestone = db.query(EmployeeMilestone).filter(EmployeeMilestone.id == milestone_id).first()
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")

    avatar = milestone.avatar_path or ""
    db.delete(milestone)
    db.commit()
    if avatar:
        delete_file(avatar)
    return {"message": "Milestone deleted successfully"}

