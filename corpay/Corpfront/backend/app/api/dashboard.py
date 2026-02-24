from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from typing import List, Optional, Tuple
from datetime import datetime, timezone, date, timedelta
from urllib.parse import urljoin
import os
from app.database import get_db, SessionLocal, engine, _RetryingSession
from app.models.revenue import Revenue, RevenueTrend, RevenueProportion, SharePrice
from app.models.posts import SocialPost
from app.models.employees import EmployeeMilestone
from app.models.file_upload import FileUpload, FileType
from app.models.payments import PaymentData
from app.models.system_performance import SystemPerformance
from app.models.api_config import ApiConfig
from app.schemas.revenue import RevenueResponse, RevenueTrendResponse, RevenueProportionResponse, SharePriceResponse
from app.schemas.posts import SocialPostResponse
from app.schemas.employees import EmployeeMilestoneResponse
from app.schemas.payments import PaymentDataResponse
from app.schemas.system_performance import SystemPerformanceResponse
from app.schemas.newsroom import NewsroomItemResponse
from app.services.share_price_api import SharePriceService
from app.services.newsroom_scraper import (
    fetch_corpay_newsroom,
    fetch_corpay_resources_newsroom,
    fetch_corpay_customer_stories,
)
from app.utils.cache import get, set
from app.utils.file_handler import get_storage_public_url

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _compute_api_base_url() -> str:
    """
    Resolve the public API base:
    1) API_BASE_URL env when set
    2) Railway public domain if present
    3) localhost fallback
    """
    base_env = (os.getenv("API_BASE_URL") or "").strip()
    if base_env:
        return base_env.rstrip("/")
    railway = (os.getenv("RAILWAY_PUBLIC_DOMAIN") or "").strip()
    if railway:
        return f"https://{railway}"
    return "http://localhost:8080"


_API_BASE_URL = _compute_api_base_url()


def _normalize_post_image_url(url: Optional[str]) -> Optional[str]:
    """Ensure post image_url is absolute so frontend can load LinkedIn and backend images."""
    if not url or not (url := url.strip()):
        return url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("/uploads/"):
        return urljoin(_API_BASE_URL.rstrip("/"), url)
    return urljoin("https://www.linkedin.com", url)


def _normalize_avatar_url(path: Optional[str]) -> Optional[str]:
    """Ensure employee avatar is an absolute URL (Supabase public URL or local uploads)."""
    if not path:
        return path
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return get_storage_public_url(path, _API_BASE_URL)


def _resolve_avatar_url(db: Session, stored_path: Optional[str]) -> Optional[str]:
    """
    Resolve stored avatar path to a public URL by checking FileUpload for storage_url.
    Falls back to get_storage_public_url when no upload record is found.
    """
    if not stored_path:
        return stored_path
    upload = (
        db.query(FileUpload)
        .filter(FileUpload.file_type == FileType.EMPLOYEE_PHOTO, FileUpload.stored_path == stored_path)
        .order_by(FileUpload.created_at.desc())
        .first()
    )
    if upload and upload.storage_url:
        return upload.storage_url
    return get_storage_public_url(stored_path, _API_BASE_URL)


@router.get("/revenue", response_model=RevenueResponse)
async def get_revenue(db: Session = Depends(get_db)):
    """Get current total revenue"""
    revenue = db.query(Revenue).order_by(Revenue.last_updated.desc()).first()
    if not revenue:
        # Return default if no data
        return RevenueResponse(
            total_amount=976000000.0,
            percentage_change=12.5,
            last_updated=datetime.now()
        )
    return revenue


def _share_price_timestamp_seconds_ago(ts: datetime) -> float:
    """Seconds since ts; safe for timezone-aware or naive ts."""
    now = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (now - ts).total_seconds()


def _max_share_price_age_seconds() -> int:
    """How old a scraped share price can be before we refresh. Default 60s (1 minute)."""
    try:
        val = int(os.getenv("SHARE_PRICE_MAX_AGE_SECONDS", "60").strip())
        return val if val > 0 else 60
    except Exception:
        return 60


def _prune_share_prices(db: Session, keep: int = 5) -> None:
    """
    Keep only the latest `keep` scraped rows and remove manual rows.
    This limits stale data lingering in the DB and ensures fallback uses recent scrape.
    """
    try:
        db.query(SharePrice).filter(SharePrice.api_source == "manual").delete()
        latest_ids_subq = (
            db.query(SharePrice.id)
            .filter(SharePrice.api_source != "manual")
            .order_by(SharePrice.timestamp.desc())
            .limit(keep)
            .subquery()
        )
        db.query(SharePrice).filter(
            SharePrice.api_source != "manual",
            ~SharePrice.id.in_(latest_ids_subq),
        ).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()


def _purge_old_share_prices(max_age_seconds: int) -> None:
    """Remove scraped rows older than max_age_seconds and delete all manual rows."""
    raw_db = SessionLocal()
    db = _RetryingSession(raw_db)
    try:
        db.query(SharePrice).filter(SharePrice.api_source == "manual").delete()
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        db.query(SharePrice).filter(
            SharePrice.api_source != "manual",
            SharePrice.timestamp < cutoff,
        ).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _get_last_share_price_read_only() -> Tuple[Optional[SharePrice], bool]:
    """
    Phase 1: Read-only DB query. Opens session, reads latest SharePrice, closes session.
    Returns (last_row, should_scrape). should_scrape is True when we need to run the scraper
    (no scraped row, or row older than max_age).
    """
    last_exc = None
    for attempt in range(3):
        raw_db = SessionLocal()
        db = _RetryingSession(raw_db)
        try:
            last_scraped = (
                db.query(SharePrice)
                .filter(SharePrice.api_source != "manual")
                .order_by(SharePrice.timestamp.desc())
                .first()
            )
            max_age = _max_share_price_age_seconds()
            if last_scraped and _share_price_timestamp_seconds_ago(last_scraped.timestamp) < max_age:
                return (last_scraped, False)
            return (last_scraped, True)
        except Exception as e:
            last_exc = e
            try:
                db.rollback()
            except Exception:
                pass
            try:
                db.close()
            except Exception:
                pass
            engine.dispose()
            continue
        finally:
            try:
                db.close()
            except Exception:
                pass
    return (None, True)


def _return_last_share_price_or_fallback() -> SharePriceResponse:
    """
    Error handling: return last known DB value, or hardcoded fallback only if no row exists.
    Opens a new short-lived session, queries latest SharePrice, closes session.
    """
    last_exc = None
    for attempt in range(3):
        raw_db = SessionLocal()
        db = _RetryingSession(raw_db)
        try:
            last_row = (
                db.query(SharePrice)
                .filter(SharePrice.api_source != "manual")
                .order_by(SharePrice.timestamp.desc())
                .first()
            )
            if last_row:
                return SharePriceResponse.model_validate(last_row)
            return SharePriceResponse(
                price=1482.35,
                change_percentage=1.24,
                timestamp=datetime.now(timezone.utc),
            )
        except Exception as e:
            last_exc = e
            try:
                db.rollback()
            except Exception:
                pass
            try:
                db.close()
            except Exception:
                pass
            engine.dispose()
            continue
        finally:
            try:
                db.close()
            except Exception:
                pass
    return SharePriceResponse(
        price=1482.35,
        change_percentage=1.24,
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/share-price", response_model=SharePriceResponse)
async def get_share_price():
    """
    Get current share price. Uses read-only session, closes before scraping,
    then opens a new session only to write scraped data. On any error returns last known DB value.
    """
    try:
        max_age = _max_share_price_age_seconds()
        try:
            _purge_old_share_prices(max_age)
        except Exception as e:
            if isinstance(e, OperationalError) or "ssl" in str(e).lower():
                pass
            else:
                raise

        last_row, should_scrape = _get_last_share_price_read_only()
        if not should_scrape and last_row:
            return SharePriceResponse.model_validate(last_row)
        if should_scrape:
            api_data = await SharePriceService.get_share_price(use_cache=False)
            raw_db = SessionLocal()
            db = _RetryingSession(raw_db)
            try:
                # Remove existing non-manual rows so we always return the freshest scrape
                db.query(SharePrice).filter(SharePrice.api_source != "manual").delete()
                new_share_price = SharePrice(
                    price=api_data["price"],
                    change_percentage=api_data["change_percentage"],
                    api_source=api_data.get("api_source", "web_scrape"),
                )
                db.add(new_share_price)
                db.commit()
                db.refresh(new_share_price)
                # Cleanup: drop manual rows and keep only the latest 5 scraped rows
                _prune_share_prices(db, keep=5)
                return SharePriceResponse.model_validate(new_share_price)
            finally:
                db.close()
        if last_row:
            return SharePriceResponse.model_validate(last_row)
        return _return_last_share_price_or_fallback()
    except Exception:
        import traceback
        traceback.print_exc()
        return _return_last_share_price_or_fallback()


@router.get("/card-titles")
async def get_card_titles(db: Session = Depends(get_db)):
    """Get configurable dashboard card titles and subtitles for payments and system performance."""
    default_payments = "Payments Processed Today"
    default_system = "System Performance"
    default_payments_amount_subtitle = "Amount Processed"
    default_payments_transactions_subtitle = "Transactions"

    config_keys = [
        "dashboard_payments_title",
        "dashboard_system_title",
        "dashboard_payments_amount_subtitle",
        "dashboard_payments_transactions_subtitle",
    ]
    configs = (
        db.query(ApiConfig)
        .filter(ApiConfig.config_key.in_(config_keys))
        .all()
    )

    titles = {
        "payments_title": default_payments,
        "system_performance_title": default_system,
        "payments_amount_subtitle": default_payments_amount_subtitle,
        "payments_transactions_subtitle": default_payments_transactions_subtitle,
    }

    for cfg in configs:
        # Allow empty string so user can clear custom text (we still overwrite default)
        if cfg.config_value is None:
            continue
        if cfg.config_key == "dashboard_payments_title":
            titles["payments_title"] = cfg.config_value
        elif cfg.config_key == "dashboard_system_title":
            titles["system_performance_title"] = cfg.config_value
        elif cfg.config_key == "dashboard_payments_amount_subtitle":
            titles["payments_amount_subtitle"] = cfg.config_value
        elif cfg.config_key == "dashboard_payments_transactions_subtitle":
            titles["payments_transactions_subtitle"] = cfg.config_value

    return titles


@router.get("/revenue-trends", response_model=List[RevenueTrendResponse])
async def get_revenue_trends(db: Session = Depends(get_db)):
    """Get revenue trends for chart"""
    current_year = datetime.now().year
    trends = db.query(RevenueTrend).filter(
        RevenueTrend.year == current_year
    ).all()
    
    if not trends:
        # Return default data (already in calendar order Jan–Dec)
        return [
            RevenueTrendResponse(month="Jan", value=70, highlight=False),
            RevenueTrendResponse(month="Feb", value=72, highlight=False),
            RevenueTrendResponse(month="Mar", value=75, highlight=False),
            RevenueTrendResponse(month="Apr", value=92, highlight=True),
            RevenueTrendResponse(month="May", value=73, highlight=False),
            RevenueTrendResponse(month="Jun", value=87, highlight=False),
            RevenueTrendResponse(month="Jul", value=89, highlight=False),
            RevenueTrendResponse(month="Aug", value=72, highlight=False),
            RevenueTrendResponse(month="Sep", value=105, highlight=True),
            RevenueTrendResponse(month="Oct", value=88, highlight=False),
            RevenueTrendResponse(month="Nov", value=91, highlight=False),
            RevenueTrendResponse(month="Dec", value=83, highlight=False),
        ]
    
    # Sort trends in calendar order Jan–Dec based on the (normalized)
    # three‑letter month abbreviation stored in the database.
    month_order = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    month_index = {m: i for i, m in enumerate(month_order)}

    def month_sort_key(trend: RevenueTrend) -> int:
        # Normalize just in case: take first 3 chars and title‑case
        month_label = (trend.month or "")[:3].title()
        return month_index.get(month_label, 99)

    trends.sort(key=month_sort_key)
    
    # Automatically highlight the top 3 months by value
    # so the frontend can render them with a different color.
    sorted_by_value = sorted(trends, key=lambda t: t.value, reverse=True)
    top_three_ids = {t.id for t in sorted_by_value[:3]}

    for trend in trends:
        trend.highlight = trend.id in top_three_ids

    return trends


@router.get("/revenue-proportions", response_model=List[RevenueProportionResponse])
async def get_revenue_proportions(db: Session = Depends(get_db)):
    """Get revenue proportions for pie chart"""
    proportions = db.query(RevenueProportion).all()
    
    if not proportions:
        # Return default data
        return [
            RevenueProportionResponse(category="Fleet", percentage=40, color="#981239"),
            RevenueProportionResponse(category="Corporate", percentage=35, color="#3D1628"),
            RevenueProportionResponse(category="Lodging", percentage=25, color="#E6E8E7"),
        ]
    
    return proportions


@router.get("/posts", response_model=List[SocialPostResponse])
async def get_corpay_posts(limit: int = 10, db: Session = Depends(get_db)):
    """Get Corpay posts - only from database (manually added by admin). No external API."""
    try:
        db_posts = db.query(SocialPost).filter(
            SocialPost.post_type == "corpay"
        ).filter(
            SocialPost.is_active == 1
        ).order_by(SocialPost.created_at.desc()).limit(limit).all()
        
        return [
            SocialPostResponse.model_validate(p).model_copy(
                update={"image_url": _normalize_post_image_url(getattr(p, "image_url", None))}
            )
            for p in db_posts
        ]
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error fetching Corpay posts: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []


@router.get("/cross-border-posts", response_model=List[SocialPostResponse])
async def get_cross_border_posts(limit: int = 10, db: Session = Depends(get_db)):
    """Get Cross-Border posts - only from database (manually added by admin). No external API."""
    try:
        db_posts = db.query(SocialPost).filter(
            SocialPost.post_type == "cross_border"
        ).filter(
            SocialPost.is_active == 1
        ).order_by(SocialPost.created_at.desc()).limit(limit).all()
        
        return [
            SocialPostResponse.model_validate(p).model_copy(
                update={"image_url": _normalize_post_image_url(getattr(p, "image_url", None))}
            )
            for p in db_posts
        ]
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error fetching Cross-Border posts: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []


@router.get("/employees", response_model=List[EmployeeMilestoneResponse])
async def get_employee_milestones(limit: int = 20, db: Session = Depends(get_db)):
    """Get employee milestones for dashboard. Excludes only explicitly inactive (is_active=0)."""
    from sqlalchemy import or_
    try:
        milestones = (
            db.query(EmployeeMilestone)
            .filter(or_(
                EmployeeMilestone.is_active == 1,
                EmployeeMilestone.is_active.is_(None),
                EmployeeMilestone.is_active != 0,
            ))
            .order_by(EmployeeMilestone.milestone_date.desc())
            .limit(limit)
            .all()
        )
        for m in milestones:
            stored = getattr(m, "avatar_path", None)
            m.avatar_path = _resolve_avatar_url(db, stored) if stored else None
        return milestones
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("get_employee_milestones failed: %s", e)
        try:
            milestones = (
                db.query(EmployeeMilestone)
                .order_by(EmployeeMilestone.milestone_date.desc())
                .limit(limit)
                .all()
            )
            for m in milestones:
                stored = getattr(m, "avatar_path", None)
                m.avatar_path = _resolve_avatar_url(db, stored) if stored else None
            return milestones
        except Exception as e2:
            logging.getLogger(__name__).exception("get_employee_milestones fallback failed: %s", e2)
            return []


@router.get("/payments", response_model=PaymentDataResponse)
async def get_payments_today(db: Session = Depends(get_db)):
    """Get today's payment data"""
    try:
        today = date.today()
        payment = db.query(PaymentData).filter(PaymentData.date == today).first()
        
        if not payment:
            # Return default if no data
            return PaymentDataResponse(
                id=0,
                amount_processed=428000000.0,  # ₹42.8 Cr
                transaction_count=19320,
                date=today,
                created_at=datetime.now()
            )
        
        # Convert SQLAlchemy model to Pydantic response
        return PaymentDataResponse(
            id=payment.id,
            amount_processed=payment.amount_processed,
            transaction_count=payment.transaction_count,
            date=payment.date,
            created_at=payment.created_at
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        # Return default on error
        return PaymentDataResponse(
            id=0,
            amount_processed=428000000.0,
            transaction_count=19320,
            date=date.today(),
            created_at=datetime.now()
        )


@router.get("/system-performance", response_model=SystemPerformanceResponse)
async def get_system_performance(db: Session = Depends(get_db)):
    """Get latest system performance metrics"""
    try:
        performance = db.query(SystemPerformance).order_by(
            SystemPerformance.timestamp.desc()
        ).first()
        
        if not performance:
            # Return default if no data
            return SystemPerformanceResponse(
                id=0,
                uptime_percentage=99.985,
                success_rate=99.62,
                timestamp=datetime.now()
            )
        
        # Convert SQLAlchemy model to Pydantic response
        return SystemPerformanceResponse(
            id=performance.id,
            uptime_percentage=performance.uptime_percentage,
            success_rate=performance.success_rate,
            timestamp=performance.timestamp
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        # Return default on error
        return SystemPerformanceResponse(
            id=0,
            uptime_percentage=99.985,
            success_rate=99.62,
            timestamp=datetime.now()
        )


def _newsroom_agent_log(location: str, message: str, data: dict, hypothesis_id: str = ""):
    # region agent log
    try:
        import json
        import time as _t
        _path = (os.getenv("APP_DEBUG_LOG_PATH") or "").strip()
        if not _path:
            return
        payload = {"id": f"log_{int(_t.time()*1000)}", "timestamp": int(_t.time()*1000), "location": location, "message": message, "data": data}
        if hypothesis_id:
            payload["hypothesisId"] = hypothesis_id
        with open(_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # endregion agent log


@router.get("/newsroom", response_model=List[NewsroomItemResponse])
async def get_newsroom_items(limit: int = 12) -> List[NewsroomItemResponse]:
    """
    Get latest items from the public Corpay corporate newsroom.
    
    Fetches with depth 20 from source (so Feb 11 etc. behind Featured items are included),
    then returns up to `limit` (default 12). Cached briefly for verification.
    On scraper/request error, returns last known cached value if any; otherwise [].
    """
    cache_key = f"newsroom_{limit}"
    cached = get(cache_key)
    # region agent log
    if cached is not None:
        _newsroom_agent_log("dashboard.py:get_newsroom_items", "Cache HIT", {"cache_key": cache_key, "cached_count": len(cached)}, "H4")
    else:
        _newsroom_agent_log("dashboard.py:get_newsroom_items", "Cache MISS, calling scraper", {"cache_key": cache_key}, "H4")
    # endregion agent log
    if cached is not None:
        return cached
    try:
        items = await fetch_corpay_newsroom(limit=20)
        result = [NewsroomItemResponse(**item) for item in items[:limit]]
        set(cache_key, result, ttl_seconds=10)
        return result
    except Exception:
        last_cached = get(cache_key)
        if last_cached is not None:
            return last_cached
        return []


@router.get("/resources-newsroom", response_model=List[NewsroomItemResponse])
async def get_resources_newsroom_items(limit: int = 4) -> List[NewsroomItemResponse]:
    """
    Get latest items from the Corpay Resources → Newsroom page via web scraping.

    Source: `https://www.corpay.com/resources/newsroom?page=2`
    Returns up to `limit` items with official url for each. No fallback list.
    When scraper returns empty or errors, returns last known cached result if any; otherwise [].
    """
    cache_key = f"resources_newsroom_{limit}"
    cached = get(cache_key)
    try:
        items = await fetch_corpay_resources_newsroom(limit=limit)
        if not items:
            return cached if cached is not None else []
        result = [NewsroomItemResponse(id=idx, **item) for idx, item in enumerate(items)]
        set(cache_key, result, ttl_seconds=300)
        return result
    except Exception:
        last_cached = get(cache_key)
        if last_cached is not None:
            return last_cached
        return []


# Fallback when scraper returns empty (e.g. JS-rendered page). From corpay.com/resources/customer-stories.
CUSTOMER_STORIES_FALLBACK = [
    {"title": "Omni Hotels & Resorts", "url": "https://www.corpay.com/resources/customer-stories/omni-hotels-and-resorts", "category": "Commercial Cards", "excerpt": "A luxury hotel brand earns $1.3M in rebates and cuts check payments by over 50% through their partnership with Corpay."},
    {"title": "Thirty Madison", "url": "https://www.corpay.com/resources/customer-stories/thirty-madison", "category": "Payments Automation", "excerpt": "The virtual-first healthcare company behind Nurx, Keeps, and Cove—centralized AP with Corpay to manage ~10 entities and multiple bank accounts in one place."},
    {"title": "Ewing Automotive", "url": "https://www.corpay.com/resources/customer-stories/ewing-automotive", "category": "Commercial Cards", "excerpt": "See how Ewing Automotive modernized AP, reduced fraud risk, and earned monthly rebates with Corpay's full-service automation platform."},
    {"title": "Scaling Internet Company", "url": "https://www.corpay.com/resources/customer-stories", "category": "Corpay Complete", "excerpt": "Scaling internet company pockets savings of $3.5M per month with Corpay Complete's end-to-end functionality."},
    {"title": "Aluminium Duffel", "url": "https://www.corpay.com/resources/customer-stories", "category": "Cross-Border", "excerpt": "Treasury department approached banks and brokers to provide credit lines and technical support in the use of FX derivatives."},
]


@router.get("/customer-stories", response_model=List[NewsroomItemResponse])
async def get_customer_stories(limit: int = 12) -> List[NewsroomItemResponse]:
    """
    Get case studies from Corpay Customer Stories.

    Source: https://www.corpay.com/resources/customer-stories
    Fetches multiple pages so every new case study posted there is included.
    When the live scrape returns empty, returns a fallback list so the UI always has content.
    Cached for 5 minutes; new case studies will appear after cache expiry or refresh.
    """
    cache_key = f"customer_stories_{limit}"
    cached = get(cache_key)
    if cached is not None:
        return cached
    items = await fetch_corpay_customer_stories(limit=limit)
    if not items:
        items = CUSTOMER_STORIES_FALLBACK[:limit]
    # Scraper returns title, url, excerpt, category (no date)
    result = [NewsroomItemResponse(title=item["title"], url=item["url"], date=None, category=item.get("category"), excerpt=item.get("excerpt")) for item in items]
    set(cache_key, result, ttl_seconds=300)
    return result

