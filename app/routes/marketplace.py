# app/routes/marketplace.py
import logging
import json
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.database.models import MarketplacePaginationScan, MarketplacePostScan, MarketplacePost, BotProfile, BotPurpose, ScanStatus
from app.database.db import get_db, SessionLocal
from app.scrapers.marketplace_scraper import create_pagination_batches, scrape_posts
import requests
from datetime import datetime
import unicodedata
from concurrent.futures import ThreadPoolExecutor
import functools


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


marketplace_api_router = APIRouter(prefix="/api/marketplace-scan", tags=["API", "Marketplace Scan"])


# Pydantic models
class MarketplacePaginationScanCreate(BaseModel):
    scan_name: str
    pagination_url: str
    max_page: int


class MarketplacePostScanCreate(BaseModel):
    scan_name: str
    pagination_scan_name: str


# Get all pagination scans
@marketplace_api_router.get("/list")
async def get_pagination_scans(db: Session = Depends(get_db)):
    try:
        scans = db.query(MarketplacePaginationScan).all()
        logger.info(f"Fetched {len(scans)} pagination scans")
        response_data = [
            {
                "id": scan.id,
                "scan_name": scan.scan_name,
                "pagination_url": scan.pagination_url,
                "max_page": scan.max_page,
                "batches": json.loads(scan.batches) if scan.batches else {},
                "timestamp": scan.timestamp.isoformat()
            } for scan in scans
        ]
        return JSONResponse(content=response_data, status_code=200)
    except Exception as e:
        logger.error(f"Error fetching pagination scans: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Create a pagination scan
@marketplace_api_router.post("/enumerate")
async def enumerate_pages(scan: MarketplacePaginationScanCreate, request: Request, db: Session = Depends(get_db)):
    try:
        if db.query(MarketplacePaginationScan).filter(MarketplacePaginationScan.scan_name == scan.scan_name).first():
            request.session["messages"] = [{"text": f"Scan name {scan.scan_name} already exists", "category": "error"}]
            logger.warning(f"Attempted to create duplicate pagination scan: {scan.scan_name}")
            raise HTTPException(status_code=400, detail="Scan name already exists")

        batches = create_pagination_batches(scan.pagination_url, scan.max_page)
        logger.info(f"Created pagination batches for scan {scan.scan_name}: {len(batches)} batches")
        db_scan = MarketplacePaginationScan(
            scan_name=scan.scan_name,
            pagination_url=scan.pagination_url,
            max_page=scan.max_page,
            batches=batches
        )
        db.add(db_scan)
        db.commit()
        db.refresh(db_scan)
        logger.info(f"Pagination scan {scan.scan_name} created successfully, ID: {db_scan.id}")

        request.session["messages"] = [{"text": "Pagination scan created successfully", "category": "success"}]
        return JSONResponse(
            content={"message": "Pagination scan created", "flash": {"text": "Pagination scan created successfully", "category": "success"}},
            status_code=201
        )
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error creating pagination scan: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


# Delete a pagination scan
@marketplace_api_router.delete("/{scan_id}")
async def delete_pagination_scan(scan_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        db_scan = db.query(MarketplacePaginationScan).filter(MarketplacePaginationScan.id == scan_id).first()
        if not db_scan:
            request.session["messages"] = [{"text": "Pagination scan not found", "category": "error"}]
            logger.warning(f"Attempted to delete non-existent pagination scan ID: {scan_id}")
            raise HTTPException(status_code=404, detail="Pagination scan not found")

        db.delete(db_scan)
        db.commit()
        logger.info(f"Pagination scan ID {scan_id} deleted successfully")
        request.session["messages"] = [{"text": "Pagination scan deleted successfully", "category": "success"}]
        return JSONResponse(
            content={"message": "Pagination scan deleted", "flash": {"text": "Pagination scan deleted successfully", "category": "success"}},
            status_code=200
        )
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error deleting pagination scan: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


# Get all post scans
@marketplace_api_router.get("/posts/list")
async def get_post_scans(db: Session = Depends(get_db)):
    try:
        scans = db.query(MarketplacePostScan).all()
        logger.info(f"Fetched {len(scans)} post scans")
        response_data = [
            {
                "id": scan.id,
                "scan_name": scan.scan_name,
                "pagination_scan_name": scan.pagination_scan_name,
                "start_date": scan.start_date.isoformat() if scan.start_date else None,
                "completion_date": scan.completion_date.isoformat() if scan.completion_date else None,
                "status": scan.status.value,
                "timestamp": scan.timestamp.isoformat()
            } for scan in scans
        ]
        return JSONResponse(content=response_data, status_code=200)
    except Exception as e:
        logger.error(f"Error fetching post scans: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Get status of a specific post scan
@marketplace_api_router.get("/posts/{scan_id}/status")
async def get_post_scan_status(scan_id: int, db: Session = Depends(get_db)):
    try:
        db_scan = db.query(MarketplacePostScan).filter(MarketplacePostScan.id == scan_id).first()
        if not db_scan:
            logger.warning(f"Post scan ID {scan_id} not found")
            raise HTTPException(status_code=404, detail="Post scan not found")
        logger.info(f"Fetched status for post scan ID {scan_id}: {db_scan.status.value}")
        return JSONResponse(
            content={
                "id": db_scan.id,
                "scan_name": db_scan.scan_name,
                "status": db_scan.status.value
            },
            status_code=200
        )
    except Exception as e:
        logger.error(f"Error fetching status for post scan ID {scan_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Create a post scan
@marketplace_api_router.post("/posts/enumerate")
async def enumerate_posts(scan: MarketplacePostScanCreate, request: Request, db: Session = Depends(get_db)):
    try:
        if db.query(MarketplacePostScan).filter(MarketplacePostScan.scan_name == scan.scan_name).first():
            request.session["messages"] = [{"text": f"Scan name {scan.scan_name} already exists", "category": "error"}]
            logger.warning(f"Attempted to create duplicate post scan: {scan.scan_name}")
            raise HTTPException(status_code=400, detail="Scan name already exists")

        pagination_scan = db.query(MarketplacePaginationScan).filter(MarketplacePaginationScan.scan_name == scan.pagination_scan_name).first()
        if not pagination_scan:
            request.session["messages"] = [{"text": f"Pagination scan {scan.pagination_scan_name} not found", "category": "error"}]
            logger.warning(f"Pagination scan not found: {scan.pagination_scan_name}")
            raise HTTPException(status_code=404, detail="Pagination scan not found")

        active_bots = db.query(BotProfile).filter(
            BotProfile.purpose == BotPurpose.SCRAPE_MARKETPLACE,
            BotProfile.session.isnot(None)
        ).all()
        if not active_bots:
            request.session["messages"] = [{"text": "No active bots with scrape_marketplace purpose found", "category": "error"}]
            logger.warning("No active scrape_marketplace bots found")
            raise HTTPException(status_code=400, detail="No active bots available")

        db_scan = MarketplacePostScan(
            scan_name=scan.scan_name,
            pagination_scan_name=scan.pagination_scan_name,
            status=ScanStatus.STOPPED
        )
        db.add(db_scan)
        db.commit()
        db.refresh(db_scan)
        logger.info(f"Post scan {scan.scan_name} created successfully, ID: {db_scan.id}")

        request.session["messages"] = [{"text": "Post scan created successfully", "category": "success"}]
        return JSONResponse(
            content={"message": "Post scan created", "flash": {"text": "Post scan created successfully", "category": "success"}},
            status_code=201
        )
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error creating post scan: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


# Start a post scan
@marketplace_api_router.post("/posts/{scan_id}/start")
async def start_post_scan(scan_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        db_scan = db.query(MarketplacePostScan).filter(MarketplacePostScan.id == scan_id).first()
        if not db_scan:
            request.session["messages"] = [{"text": "Post scan not found", "category": "error"}]
            logger.warning(f"Post scan ID {scan_id} not found")
            raise HTTPException(status_code=404, detail="Post scan not found")

        if db_scan.status == ScanStatus.RUNNING:
            request.session["messages"] = [{"text": "Scan is already running", "category": "error"}]
            logger.warning(f"Attempted to start running scan: {db_scan.scan_name}")
            raise HTTPException(status_code=400, detail="Scan is already running")

        # Check for active bots
        active_bots = db.query(BotProfile).filter(
            BotProfile.purpose == BotPurpose.SCRAPE_MARKETPLACE,
            BotProfile.session.isnot(None)
        ).all()
        if not active_bots:
            request.session["messages"] = [{"text": "No active bots with scrape_marketplace purpose found", "category": "error"}]
            logger.warning(f"No active scrape_marketplace bots found for scan ID {scan_id}")
            raise HTTPException(status_code=400, detail="No active bots available")

        logger.info(f"Found {len(active_bots)} active bots for scan ID {scan_id}: {[bot.username for bot in active_bots]}")

        # Get pagination scan batches
        pagination_scan = db.query(MarketplacePaginationScan).filter(
            MarketplacePaginationScan.scan_name == db_scan.pagination_scan_name
        ).first()
        if not pagination_scan:
            request.session["messages"] = [{"text": "Associated pagination scan not found", "category": "error"}]
            logger.warning(f"Pagination scan {db_scan.pagination_scan_name} not found for post scan ID {scan_id}")
            raise HTTPException(status_code=404, detail="Pagination scan not found")

        batches = json.loads(pagination_scan.batches) if pagination_scan.batches else {}
        if not batches:
            request.session["messages"] = [{"text": "No batches found for pagination scan", "category": "error"}]
            logger.warning(f"No batches found for pagination scan {db_scan.pagination_scan_name}")
            raise HTTPException(status_code=400, detail="No batches available")

        logger.info(f"Starting post scan {db_scan.scan_name} (ID: {scan_id}) with {len(batches)} batches: {list(batches.keys())}")

        # Update scan status
        db_scan.status = ScanStatus.RUNNING
        db_scan.start_date = datetime.utcnow()
        db_scan.completion_date = None
        db.commit()
        logger.info(f"Post scan {db_scan.scan_name} (ID: {scan_id}) status updated to RUNNING")

        # Run scraping in background with concurrent batch processing
        async def scrape_batches():
            try:
                # Initialize bot availability
                available_bots = active_bots.copy()
                batch_queue = [(key, urls) for key, urls in batches.items()]

                def sync_scrape_batch(bot, batch_key, urls, scan_id):
                    with SessionLocal() as batch_db:  # Create new session for each batch
                        logger.info(f"Bot {bot.username} (ID: {bot.id}) starting batch {batch_key} ({len(urls)} URLs)")
                        session = requests.Session()
                        session_cookie = bot.session.split('=')[1] if '=' in bot.session else bot.session
                        session.cookies.set('session', session_cookie)
                        logger.debug(f"Bot {bot.username} using session cookie: {session_cookie[:20]}... and proxy: {bot.tor_proxy}")
                        try:
                            logger.debug(f"Scraping batch {batch_key} with URLs: {urls}")
                            posts_data_raw = scrape_posts(session, bot.tor_proxy, bot.user_agent, urls)
                            try:
                                posts_data = json.loads(posts_data_raw)
                            except json.JSONDecodeError as e:
                                logger.error(f"JSON decode error for batch {batch_key} by bot {bot.username}: {str(e)}")
                                logger.debug(f"Raw data causing JSON error: {posts_data_raw[:200]}...")
                                # Sanitize and retry parsing
                                sanitized_data = {}
                                try:
                                    raw_dict = eval(posts_data_raw) if posts_data_raw else {}
                                    for timestamp, post in raw_dict.items():
                                        # Normalize Unicode and remove control characters
                                        sanitized_title = unicodedata.normalize('NFKC', post['title']).encode('ascii', 'ignore').decode('ascii')
                                        sanitized_data[timestamp] = {
                                            'title': sanitized_title,
                                            'author': post['author'],
                                            'link': post['link']
                                        }
                                    posts_data = sanitized_data
                                    logger.info(f"Successfully sanitized JSON for batch {batch_key}")
                                except Exception as se:
                                    logger.error(f"Failed to sanitize JSON for batch {batch_key}: {str(se)}")
                                    raise

                            logger.info(f"Bot {bot.username} completed batch {batch_key}, found {len(posts_data)} posts")

                            # Save posts to database with stricter duplicate check
                            for timestamp, post in posts_data.items():
                                if not batch_db.query(MarketplacePost).filter(
                                    MarketplacePost.scan_id == scan_id,
                                    MarketplacePost.timestamp == timestamp,
                                    MarketplacePost.title == post['title'],
                                    MarketplacePost.link == post['link']
                                ).first():
                                    db_post = MarketplacePost(
                                        scan_id=scan_id,
                                        timestamp=timestamp,
                                        title=post['title'],
                                        author=post['author'],
                                        link=post['link']
                                    )
                                    batch_db.add(db_post)
                                    logger.debug(f"Bot {bot.username} added post with timestamp {timestamp} for scan ID {scan_id}")
                                else:
                                    logger.debug(f"Bot {bot.username} skipped duplicate post with timestamp {timestamp} for scan ID {scan_id}")
                            batch_db.commit()
                            logger.info(f"Bot {bot.username} saved batch {batch_key} posts to database for scan ID {scan_id}")
                        except Exception as e:
                            logger.error(f"Bot {bot.username} failed batch {batch_key} for scan ID {scan_id}: {str(e)}")
                            batch_db.rollback()
                            raise

                # Assign batches to available bots
                with ThreadPoolExecutor(max_workers=len(available_bots)) as executor:
                    tasks = []
                    for i, (batch_key, urls) in enumerate(batch_queue):
                        bot = available_bots[i % len(available_bots)]  # Cycle through bots
                        logger.info(f"Assigning batch {batch_key} to bot {bot.username} (ID: {bot.id})")
                        task = asyncio.get_event_loop().run_in_executor(
                            executor,
                            functools.partial(sync_scrape_batch, bot, batch_key, urls, db_scan.id)
                        )
                        tasks.append(task)

                    # Run all batch tasks concurrently
                    if tasks:
                        logger.info(f"Launching {len(tasks)} concurrent batch tasks")
                        await asyncio.gather(*tasks, return_exceptions=True)

                # Mark scan as completed
                with SessionLocal() as final_db:
                    db_scan_final = final_db.query(MarketplacePostScan).filter(MarketplacePostScan.id == scan_id).first()
                    db_scan_final.status = ScanStatus.COMPLETED
                    db_scan_final.completion_date = datetime.utcnow()
                    final_db.commit()
                    logger.info(f"Post scan {db_scan_final.scan_name} (ID: {scan_id}) completed successfully")
            except Exception as e:
                logger.error(f"Error in scan {db_scan.scan_name} (ID: {scan_id}): {str(e)}")
                with SessionLocal() as error_db:
                    db_scan_error = error_db.query(MarketplacePostScan).filter(MarketplacePostScan.id == scan_id).first()
                    db_scan_error.status = ScanStatus.STOPPED
                    db_scan_error.completion_date = datetime.utcnow()
                    error_db.commit()
                    request.session["messages"] = [{"text": f"Scan {db_scan_error.scan_name} failed", "category": "error"}]

        # Start the scraping task
        asyncio.create_task(scrape_batches())

        request.session["messages"] = [{"text": f"Post scan {db_scan.scan_name} started", "category": "success"}]
        return JSONResponse(
            content={"message": "Post scan started", "flash": {"text": f"Post scan {db_scan.scan_name} started", "category": "success"}},
            status_code=200
        )
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error starting post scan ID {scan_id}: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


# Delete a post scan
@marketplace_api_router.delete("/posts/{scan_id}")
async def delete_post_scan(scan_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        db_scan = db.query(MarketplacePostScan).filter(MarketplacePostScan.id == scan_id).first()
        if not db_scan:
            request.session["messages"] = [{"text": "Post scan not found", "category": "error"}]
            logger.warning(f"Post scan ID {scan_id} not found")
            raise HTTPException(status_code=404, detail="Post scan not found")

        db.delete(db_scan)
        db.commit()
        logger.info(f"Post scan {db_scan.scan_name} (ID: {scan_id}) deleted")

        return JSONResponse(
            content={"message": "Post scan deleted", "flash": {"text": f"Post scan {db_scan.scan_name} deleted successfully", "category": "success"}},
            status_code=200
        )
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error deleting post scan ID {scan_id}: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


# Get posts for a scan
@marketplace_api_router.get("/posts/{scan_id}/posts")
async def get_scan_posts(scan_id: int, db: Session = Depends(get_db)):
    try:
        db_scan = db.query(MarketplacePostScan).filter(MarketplacePostScan.id == scan_id).first()
        if not db_scan:
            logger.warning(f"Post scan ID {scan_id} not found")
            raise HTTPException(status_code=404, detail="Post scan not found")

        posts = db.query(MarketplacePost).filter(MarketplacePost.scan_id == scan_id).all()
        logger.info(f"Fetched {len(posts)} posts for scan ID {scan_id}")
        response_data = [
            {
                "id": post.id,
                "timestamp": post.timestamp,
                "title": post.title,
                "author": post.author,
                "link": post.link
            } for post in posts
        ]
        return JSONResponse(content=response_data, status_code=200)
    except Exception as e:
        logger.error(f"Error fetching posts for scan ID {scan_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")