# app/routes/watchlist.py
import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from app.database.models import Watchlist, WatchlistProfileScan, BotProfile, BotPurpose
from app.database.db import get_db, engine
from datetime import datetime
from pydantic import BaseModel
from typing import List
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.scrapers.profile_scraper import scrape_profile
import json


# Enable APScheduler debug logging
logging.basicConfig(level=logging.INFO)
logging.getLogger('apscheduler').setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)


watchlist_api_router = APIRouter(prefix="/api/watchlist-api", tags=["API", "Watchlist"])


# Pydantic models
class WatchlistCreate(BaseModel):
    target_name: str
    profile_link: str
    priority: str
    frequency: str

class WatchlistUpdate(BaseModel):
    target_name: str
    profile_link: str
    priority: str
    frequency: str

class WatchlistResponse(BaseModel):
    id: int
    target_name: str
    profile_link: str
    priority: str
    frequency: str
    timestamp: datetime

    class Config:
        from_attributes = True

class WatchlistProfileScanResponse(BaseModel):
    id: int
    watchlist_id: int
    scan_timestamp: datetime
    profile_data: dict

    class Config:
        from_attributes = True


# Scheduler setup (initialize globally)
scheduler = AsyncIOScheduler()


# Map stored frequency values to labels
FREQUENCY_TO_LABEL = {
    "every 5 minutes": "critical",
    "every 1 hour": "very high",
    "every 6 hours": "high",
    "every 12 hours": "medium",
    "every 24 hours": "low"
}

# Map frequency labels to intervals (in seconds)
FREQUENCY_MAP = {
    "critical": 5 * 60,
    "very high": 60 * 60,
    "high": 6 * 60 * 60,
    "medium": 12 * 60 * 60,
    "low": 24 * 60 * 60
}

def schedule_all_tasks(db: Session):
    try:
        watchlist_items = db.query(Watchlist).all()
        for item in watchlist_items:
            schedule_task(db, item)
        logger.info(f"Scheduled {len(watchlist_items)} tasks")
    except Exception as e:
        logger.error(f"Error scheduling tasks: {str(e)}", exc_info=True)


def schedule_task(db: Session, watchlist_item: Watchlist):
    frequency_label = FREQUENCY_TO_LABEL.get(watchlist_item.frequency, "low")
    interval = FREQUENCY_MAP.get(frequency_label, 24 * 60 * 60)
    scheduler.add_job(
        scrape_and_save,
        trigger=IntervalTrigger(seconds=interval),
        args=[watchlist_item.id],
        id=f"scrape_{watchlist_item.id}",
        replace_existing=True
    )
    logger.info(f"Scheduled scraping for watchlist item {watchlist_item.id} every {interval} seconds ({frequency_label})")


async def scrape_and_save(watchlist_id: int, db: Session = None):
    logger.debug(f"Starting scrape_and_save for watchlist item {watchlist_id}")
    # Create a new session if none provided for scheduler
    db_session = db if db else Session(engine)
    try:
        watchlist_item = db_session.query(Watchlist).filter(Watchlist.id == watchlist_id).first()
        if not watchlist_item:
            logger.error(f"Watchlist item {watchlist_id} not found")
            return

        # Count available bots for debugging
        bot_count = db_session.query(BotProfile).filter(
            BotProfile.purpose == BotPurpose.SCRAPE_PROFILE,
            BotProfile.session.isnot(None)
        ).count()
        logger.debug(f"Available bots for SCRAPE_PROFILE with active session: {bot_count}")

        # Select a random bot with SCRAPE_PROFILE purpose and active session
        bot = db_session.query(BotProfile).filter(
            BotProfile.purpose == BotPurpose.SCRAPE_PROFILE,
            BotProfile.session.isnot(None)
        ).order_by(func.random()).first()
        if not bot:
            logger.error("No bot with SCRAPE_PROFILE purpose and active session found")
            return

        logger.debug(f"Selected bot ID {bot.id} with user_agent '{bot.user_agent}' and tor_proxy '{bot.tor_proxy}' for watchlist item {watchlist_id}")

        # Split 'session=' prefix from bot.session
        session_cookie = bot.session.split("session=", 1)[1] if bot.session and "session=" in bot.session else bot.session

        scrape_result = scrape_profile(
            url=watchlist_item.profile_link,
            session_cookie=session_cookie,
            user_agent=bot.user_agent,
            tor_proxy=bot.tor_proxy,
            scrape_option=watchlist_item.priority
        )

        if "error" in scrape_result:
            logger.error(f"Scraping failed for watchlist item {watchlist_id} with bot ID {bot.id}: {scrape_result['error']}")
            return

        # Log the scrape result keys for debugging
        logger.debug(f"Scrape result keys for watchlist item {watchlist_id}: {list(scrape_result.keys())}")
        if 'posts' in scrape_result:
            logger.debug(f"Post keys: {[list(post.keys()) for post in scrape_result['posts'][:1]]}")
        if 'comments' in scrape_result:
            logger.debug(f"Comment keys: {[list(comment.keys()) for comment in scrape_result['comments'][:1]]}")

        # Validate scrape result
        if not scrape_result.get('profile') and not scrape_result.get('posts') and not scrape_result.get('comments'):
            logger.warning(f"Empty scrape result for watchlist item {watchlist_id} with bot ID {bot.id}")
            return

        new_scan = WatchlistProfileScan(
            watchlist_id=watchlist_id,
            scan_timestamp=datetime.utcnow(),
            profile_data=scrape_result
        )
        db_session.add(new_scan)
        db_session.commit()
        logger.info(f"Saved scan result for watchlist item {watchlist_id} with bot ID {bot.id}")
    except Exception as e:
        logger.error(f"Error in scrape_and_save for watchlist item {watchlist_id}: {str(e)}", exc_info=True)
        db_session.rollback()
    finally:
        if not db:  # Only close session if we created it
            db_session.close()


@watchlist_api_router.get("/items", response_model=List[WatchlistResponse])
async def get_watchlist(db: Session = Depends(get_db)):
    try:
        items = db.query(Watchlist).all()
        return items
    except Exception as e:
        logger.error(f"Error fetching watchlist: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@watchlist_api_router.get("/items/{item_id}", response_model=WatchlistResponse)
async def get_watchlist_item(item_id: int, db: Session = Depends(get_db)):
    try:
        db_item = db.query(Watchlist).filter(Watchlist.id == item_id).first()
        if not db_item:
            raise HTTPException(status_code=404, detail="Item not found")
        return db_item
    except Exception as e:
        logger.error(f"Error fetching watchlist item: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@watchlist_api_router.post("/items", response_model=WatchlistResponse)
async def create_watchlist_item(item: WatchlistCreate, db: Session = Depends(get_db)):
    try:
        if db.query(Watchlist).filter(Watchlist.target_name == item.target_name).first():
            raise HTTPException(status_code=400, detail="Target name already exists")
        
        db_item = Watchlist(
            target_name=item.target_name,
            profile_link=item.profile_link,
            priority=item.priority.lower(),
            frequency=item.frequency.lower(),
            timestamp=datetime.utcnow()
        )
        db.add(db_item)
        db.commit()
        db.refresh(db_item)
        
        # Run an immediate scan only if no scans exist
        existing_scan = db.query(WatchlistProfileScan).filter(WatchlistProfileScan.watchlist_id == db_item.id).first()
        if not existing_scan:
            await scrape_and_save(db_item.id, db)
        
        # Schedule future scans
        schedule_task(db, db_item)
        return db_item
    except Exception as e:
        logger.error(f"Error creating watchlist item: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@watchlist_api_router.put("/items/{item_id}", response_model=WatchlistResponse)
async def update_watchlist_item(item_id: int, item: WatchlistUpdate, db: Session = Depends(get_db)):
    try:
        db_item = db.query(Watchlist).filter(Watchlist.id == item_id).first()
        if not db_item:
            raise HTTPException(status_code=404, detail="Item not found")
        
        if db.query(Watchlist).filter(Watchlist.target_name == item.target_name).filter(Watchlist.id != item_id).first():
            raise HTTPException(status_code=400, detail="Target name already exists")
        
        db_item.target_name = item.target_name
        db_item.profile_link = item.profile_link
        db_item.priority = item.priority.lower()
        db_item.frequency = item.frequency.lower()
        
        db.commit()
        db.refresh(db_item)
        schedule_task(db, db_item)
        return db_item
    except Exception as e:
        logger.error(f"Error updating watchlist item: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@watchlist_api_router.delete("/items/{item_id}")
async def delete_watchlist_item(item_id: int, db: Session = Depends(get_db)):
    try:
        db_item = db.query(Watchlist).filter(Watchlist.id == item_id).first()
        if not db_item:
            raise HTTPException(status_code=404, detail="Item not found")
        db.query(WatchlistProfileScan).filter(WatchlistProfileScan.watchlist_id == item_id).delete()
        try:
            scheduler.remove_job(f"scrape_{item_id}")
        except Exception:
            pass
        db.delete(db_item)
        db.commit()
        return {"message": "Item deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting watchlist item {item_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@watchlist_api_router.get("/scans/{watchlist_id}", response_model=List[WatchlistProfileScanResponse])
async def get_profile_scans(watchlist_id: int, db: Session = Depends(get_db)):
    try:
        scans = db.query(WatchlistProfileScan).filter(WatchlistProfileScan.watchlist_id == watchlist_id).order_by(WatchlistProfileScan.scan_timestamp.desc()).all()
        return scans
    except Exception as e:
        logger.error(f"Error fetching profile scans: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@watchlist_api_router.get("/download-scan/{scan_id}")
async def download_scan(scan_id: int, db: Session = Depends(get_db)):
    try:
        scan = db.query(WatchlistProfileScan).filter(WatchlistProfileScan.id == scan_id).first()
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        
        filename = f"scan_{scan_id}.json"
        filepath = f"/tmp/{filename}"
        with open(filepath, "w") as f:
            json.dump(scan.profile_data, f, indent=2)
        
        return FileResponse(filepath, media_type="application/json", filename=filename)
    except Exception as e:
        logger.error(f"Error downloading scan {scan_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@watchlist_api_router.on_event("startup")
async def startup_event():
    global scheduler
    if not scheduler.running:
        db = next(get_db())
        schedule_all_tasks(db)
        scheduler.start()
        logger.info("Scheduler started")
    else:
        logger.info("Scheduler already running, skipping startup")
