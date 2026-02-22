from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models.posts import SocialPost
from app.schemas.posts import SocialPostCreate, SocialPostResponse, PostFromURLRequest
from app.utils.auth import get_current_admin_user
from app.models.user import User

router = APIRouter(prefix="/api/admin/posts", tags=["admin-posts"])


@router.post("", response_model=SocialPostResponse)
async def create_post(
    post: SocialPostCreate,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Create a new social media post"""
    db_post = SocialPost(**post.dict())
    db.add(db_post)
    db.commit()
    db.refresh(db_post)
    return db_post


@router.get("", response_model=List[SocialPostResponse])
async def list_posts(
    post_type: str = None,
    limit: int = 50,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """List all posts"""
    query = db.query(SocialPost)
    if post_type:
        query = query.filter(SocialPost.post_type == post_type)
    posts = query.order_by(SocialPost.created_at.desc()).limit(limit).all()
    return posts


@router.get("/{post_id}", response_model=SocialPostResponse)
async def get_post(
    post_id: int,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Get a specific post"""
    post = db.query(SocialPost).filter(SocialPost.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


@router.put("/{post_id}", response_model=SocialPostResponse)
async def update_post(
    post_id: int,
    post: SocialPostCreate,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Update a post"""
    db_post = db.query(SocialPost).filter(SocialPost.id == post_id).first()
    if not db_post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    for key, value in post.dict().items():
        setattr(db_post, key, value)
    
    db.commit()
    db.refresh(db_post)
    return db_post


@router.delete("/{post_id}/dev")
async def delete_post_dev(post_id: int, db: Session = Depends(get_db)):
    """Delete a post (soft delete) - development mode, no auth"""
    post = db.query(SocialPost).filter(SocialPost.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    try:
        post.is_active = 0
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete post: {str(e)}",
        )
    return {"message": "Post deleted successfully"}


@router.delete("/{post_id}")
async def delete_post(
    post_id: int,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Delete a post (soft delete)"""
    post = db.query(SocialPost).filter(SocialPost.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    try:
        post.is_active = 0
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete post: {str(e)}",
        )
    return {"message": "Post deleted successfully"}


@router.post("/from-url", response_model=SocialPostResponse)
async def create_post_from_url(
    request: PostFromURLRequest,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Create a post from a LinkedIn URL (manual entry)"""
    if not request.post_url or not request.post_url.strip():
        raise HTTPException(status_code=400, detail="Post URL is required")
    
    if request.post_type not in ['corpay', 'cross_border']:
        raise HTTPException(status_code=400, detail="post_type must be 'corpay' or 'cross_border'")
    
    from datetime import datetime, timedelta
    from app.services.linkedin_url_extractor import LinkedInURLExtractor
    import logging
    
    logger = logging.getLogger(__name__)
    
    # Extract metadata from LinkedIn URL (image and caption)
    # If extraction fails, we'll still create the post with the URL
    try:
        metadata = await LinkedInURLExtractor.extract_post_metadata(request.post_url.strip())
        # Content is already limited to first two lines by the extractor
        display_content = metadata['content'].strip()
        image_url = metadata.get('image_url')
    except Exception as e:
        logger.warning(f"Failed to extract metadata from LinkedIn URL: {e}. Creating post with URL only.")
        display_content = f"LinkedIn Post: {request.post_url}"
        image_url = None
    
    # Create a post entry with extracted metadata (or fallback)
    try:
        db_post = SocialPost(
            author="Corpay" if request.post_type == "corpay" else "Corpay Cross-Border",
            content=display_content or f"LinkedIn Post: {request.post_url}",
            image_url=image_url,
            post_url=request.post_url.strip(),
            post_type=request.post_type,
            time_ago="Just now",
            source="manual",
            likes=0,
            comments=0,
            is_active=1  # Ensure post is active
        )
        
        db.add(db_post)
        db.commit()
        db.refresh(db_post)
        
        logger.info(f"Successfully created post with ID {db_post.id} from URL {request.post_url}")
        return db_post
    except Exception as e:
        logger.error(f"Error creating post in database: {e}")
        import traceback
        logger.error(traceback.format_exc())
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create post: {str(e)}")


@router.post("/from-url-dev", response_model=SocialPostResponse)
async def create_post_from_url_dev(
    request: PostFromURLRequest,
    db: Session = Depends(get_db)
):
    """Create a post from a LinkedIn URL (manual entry) - Development mode without auth"""
    if not request.post_url or not request.post_url.strip():
        raise HTTPException(status_code=400, detail="Post URL is required")
    
    if request.post_type not in ['corpay', 'cross_border']:
        raise HTTPException(status_code=400, detail="post_type must be 'corpay' or 'cross_border'")
    
    from datetime import datetime, timedelta
    from app.services.linkedin_url_extractor import LinkedInURLExtractor
    import logging
    
    logger = logging.getLogger(__name__)
    
    # Extract metadata from LinkedIn URL (image and caption)
    # If extraction fails, we'll still create the post with the URL
    try:
        metadata = await LinkedInURLExtractor.extract_post_metadata(request.post_url.strip())
        # Content is already limited to first two lines by the extractor
        display_content = metadata['content'].strip()
        image_url = metadata.get('image_url')
    except Exception as e:
        logger.warning(f"Failed to extract metadata from LinkedIn URL: {e}. Creating post with URL only.")
        display_content = f"LinkedIn Post: {request.post_url}"
        image_url = None
    
    # Create a post entry with extracted metadata (or fallback)
    try:
        db_post = SocialPost(
            author="Corpay" if request.post_type == "corpay" else "Corpay Cross-Border",
            content=display_content or f"LinkedIn Post: {request.post_url}",
            image_url=image_url,
            post_url=request.post_url.strip(),
            post_type=request.post_type,
            time_ago="Just now",
            source="manual",
            likes=0,
            comments=0,
            is_active=1  # Ensure post is active
        )
        
        db.add(db_post)
        db.commit()
        db.refresh(db_post)
        
        logger.info(f"Successfully created post with ID {db_post.id} from URL {request.post_url}")
        return db_post
    except Exception as e:
        logger.error(f"Error creating post in database: {e}")
        import traceback
        logger.error(traceback.format_exc())
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create post: {str(e)}")