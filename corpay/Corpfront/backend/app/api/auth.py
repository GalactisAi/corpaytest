from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session
from datetime import datetime
import bcrypt
from app.database import get_db
from app.models.user import User
from app.schemas.auth import Token, UserResponse, UserLogin
from app.utils.auth import create_access_token, get_current_user
from app.config import settings

router = APIRouter(prefix="/api/admin/auth", tags=["auth"])


@router.options("/login")
def login_options():
    """CORS preflight for POST /login."""
    return Response(status_code=200)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    if not hashed_password:
        return False
    try:
        ok = bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
        return ok
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    """Hash a password"""
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    out = hashed.decode("utf-8")
    return out


@router.post("/login", response_model=Token)
async def login(
    user_credentials: UserLogin,
    db: Session = Depends(get_db)
):
    """Login with email and password"""
    # Find user by email
    try:
        user = db.query(User).filter(User.email == user_credentials.email).first()
    except Exception as e:
        raise
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify password
    if not verify_password(user_credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Update last login
    user.last_login = datetime.now()
    try:
        db.commit()
    except Exception as e:
        raise
    
    # Create JWT token
    access_token = create_access_token(data={"sub": user.email})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": UserResponse.model_validate(user)
    }


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """Get current authenticated user info"""
    return current_user


@router.post("/create-admin-dev")
async def create_admin_dev(db: Session = Depends(get_db)):
    """Development endpoint to create/reset admin user (no auth required for dev)"""
    try:
        password = "Cadmin@1"
        password_hash = get_password_hash(password)
        
        # Check if admin user exists
        admin_user = db.query(User).filter(User.email == "admin@corpay.com").first()
        if not admin_user:
            # Create admin user
            admin_user = User(
                email="admin@corpay.com",
                name="Admin User",
                password_hash=password_hash,
                is_admin=1
            )
            db.add(admin_user)
            message = "Admin user created"
        else:
            # Update password and ensure is_admin is set
            admin_user.password_hash = password_hash
            admin_user.is_admin = 1
            message = "Admin user password updated"
        
        db.commit()
        return {
            "success": True,
            "message": message,
            "email": "admin@corpay.com",
            "password": "Cadmin@1"
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create/update admin user: {str(e)}"
        )