# app/routes/posts.py
import logging
import json
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from pydantic import BaseModel
from typing import List
from app.database.models import PostDetailScan, MarketplacePostScan, MarketplacePost, BotProfile, BotPurpose, ScanStatus, APIs, MarketplacePostDetails
from app.database.db import get_db, SessionLocal
from app.scrapers.post_scraper import scrape_post_details, translate_string, iab_classify
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import functools
import unicodedata
from langdetect import detect, DetectorFactory


DetectorFactory.seed = 0


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

posts_api_router = APIRouter(prefix="/api/posts-scanner", tags=["API", "Posts Scanner"])



# Pydantic models
class PostScanCreate(BaseModel):
    scan_name: str
    source_scan_name: str
    batch_size: int
    site_url: str


class PostDownloadRequest(BaseModel):
    post_ids: List[int]


# Get all post detail scans
@posts_api_router.get("/list")
async def get_post_scans(db: Session = Depends(get_db)):
    try:
        scans = db.query(
            PostDetailScan.id,
            PostDetailScan.scan_name,
            PostDetailScan.source_scan_name,
            PostDetailScan.start_date,
            PostDetailScan.completion_date,
            PostDetailScan.status,
            PostDetailScan.timestamp,
            func.count(MarketplacePostDetails.id).label('scraped_posts')
        ).outerjoin(
            MarketplacePostDetails,
            PostDetailScan.id == MarketplacePostDetails.scan_id
        ).group_by(
            PostDetailScan.id
        ).all()

        response_data = [
            {
                "id": scan.id,
                "scan_name": scan.scan_name,
                "source_scan_name": scan.source_scan_name,
                "start_date": scan.start_date.isoformat() if scan.start_date else None,
                "completion_date": scan.completion_date.isoformat() if scan.completion_date else None,
                "status": scan.status.value,
                "scraped_posts": scan.scraped_posts,
                "timestamp": scan.timestamp.isoformat()
            } for scan in scans
        ]
        return JSONResponse(content=response_data, status_code=200)
    except Exception as e:
        logger.error(f"Error fetching post detail scans: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Get completed post scan names for dropdown
@posts_api_router.get("/completed-post-scans")
async def get_completed_post_scans(db: Session = Depends(get_db)):
    try:
        scans = db.query(MarketplacePostScan).filter(
            MarketplacePostScan.completion_date.isnot(None),
            MarketplacePostScan.status == ScanStatus.COMPLETED
        ).all()
        scan_names = [scan.scan_name for scan in scans]
        return JSONResponse(content=scan_names, status_code=200)
    except Exception as e:
        logger.error(f"Error fetching completed post scan names: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Create a post detail scan
@posts_api_router.post("/create")
async def create_post_scan(scan: PostScanCreate, request: Request, db: Session = Depends(get_db)):
    try:
        # Check for duplicate scan name
        if db.query(PostDetailScan).filter(PostDetailScan.scan_name == scan.scan_name).first():
            request.session["messages"] = [{"text": f"Scan name {scan.scan_name} already exists", "category": "error"}]
            logger.warning(f"Attempted to create duplicate post detail scan: {scan.scan_name}")
            raise HTTPException(status_code=400, detail="Scan name already exists")

        # Verify the source post scan is completed
        source_scan = db.query(MarketplacePostScan).filter(
            MarketplacePostScan.scan_name == scan.source_scan_name,
            MarketplacePostScan.completion_date.isnot(None),
            MarketplacePostScan.status == ScanStatus.COMPLETED
        ).first()
        if not source_scan:
            request.session["messages"] = [{"text": f"Completed post scan {scan.source_scan_name} not found", "category": "error"}]
            logger.warning(f"Completed post scan not found: {scan.source_scan_name}")
            raise HTTPException(status_code=404, detail="Completed post scan not found")

        db_scan = PostDetailScan(
            scan_name=scan.scan_name,
            source_scan_name=scan.source_scan_name,
            status=ScanStatus.STOPPED,
            batch_size=scan.batch_size,
            site_url=scan.site_url
        )
        db.add(db_scan)
        db.commit()
        db.refresh(db_scan)
        
        request.session["messages"] = [{"text": "Post detail scan created successfully", "category": "success"}]
        return JSONResponse(
            content={
                "id": db_scan.id,
                "message": "Post detail scan created",
                "flash": {"text": "Post detail scan created successfully", "category": "success"}
            },
            status_code=201
        )
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error creating post detail scan: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


# Start a post detail scan
@posts_api_router.post("/{scan_id}/start")
async def start_post_scan(scan_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        # Get scan
        db_scan = db.query(PostDetailScan).filter(PostDetailScan.id == scan_id).first()
        if not db_scan:
            request.session["messages"] = [{"text": "Post detail scan not found", "category": "error"}]
            logger.warning(f"Post detail scan ID {scan_id} not found")
            raise HTTPException(status_code=404, detail="Post detail scan not found")

        if db_scan.status == ScanStatus.RUNNING:
            request.session["messages"] = [{"text": "Scan is already running", "category": "error"}]
            logger.warning(f"Attempted to start running scan: {db_scan.scan_name}")
            raise HTTPException(status_code=400, detail="Scan is already running")

        # Get API keys
        translation_api = db.query(APIs).filter(
            APIs.api_type == "translation_api",
            APIs.is_active == True
        ).first()
        
        iab_api = db.query(APIs).filter(
            APIs.api_type == "iab_api",
            APIs.is_active == True
        ).first()

        if not translation_api or not iab_api:
            request.session["messages"] = [{"text": "Required APIs (translation or IAB) not found", "category": "error"}]
            logger.warning("Missing required APIs")
            raise HTTPException(status_code=400, detail="Required APIs not found")

        # Extract API attributes to avoid session issues
        translation_api_key = translation_api.api_key
        iab_api_data = {
            "api_key": iab_api.api_key,
            "model": iab_api.model,
            "prompt": iab_api.prompt,
            "max_tokens": iab_api.max_tokens
        }

        # Get active bots
        active_bots = db.query(BotProfile).filter(
            BotProfile.purpose == BotPurpose.SCRAPE_POST,
            BotProfile.session.isnot(None),
            BotProfile.session != ""
        ).all()
        
        if not active_bots:
            request.session["messages"] = [{"text": "No active scrape_post bots found", "category": "error"}]
            logger.warning(f"No active scrape_post bots found for scan ID {scan_id}")
            raise HTTPException(status_code=400, detail="No active bots available")

        # Get posts from the source scan
        source_scan = db.query(MarketplacePostScan).filter(
            MarketplacePostScan.scan_name == db_scan.source_scan_name,
            MarketplacePostScan.completion_date.isnot(None),
            MarketplacePostScan.status == ScanStatus.COMPLETED
        ).first()
        
        if not source_scan:
            request.session["messages"] = [{"text": f"Source post scan {db_scan.source_scan_name} not found or not completed", "category": "error"}]
            logger.warning(f"Source post scan {db_scan.source_scan_name} not found or not completed")
            raise HTTPException(status_code=404, detail="Source post scan not found or not completed")

        posts = db.query(MarketplacePost).filter(MarketplacePost.scan_id == source_scan.id).all()
        if not posts:
            request.session["messages"] = [{"text": "No posts found for source scan", "category": "error"}]
            logger.warning(f"No posts found for source scan ID {source_scan.id}")
            raise HTTPException(status_code=404, detail="No posts found")

        # Extract post attributes to avoid session issues
        post_data = [(post.link, post.timestamp) for post in posts]
        logger.info(f"Extracted {len(post_data)} posts for scan ID {scan_id}")

        # Use stored batch size and site URL
        batch_size = db_scan.batch_size
        site_url = db_scan.site_url

        if not site_url:
            request.session["messages"] = [{"text": "Site URL is required", "category": "error"}]
            logger.warning("Site URL not provided")
            raise HTTPException(status_code=400, detail="Site URL is required")

        # Create batches
        batches = []
        for i in range(0, len(post_data), batch_size):
            batch_posts = post_data[i:i + batch_size]
            batches.append((f"batch_{i//batch_size + 1:03d}", batch_posts))

        # Update scan status
        db_scan.status = ScanStatus.RUNNING
        db_scan.start_date = datetime.utcnow()
        db_scan.completion_date = None
        db.commit()

        # Track errors for scan status
        scan_errors = []

        # Run scraping concurrently
        async def scrape_post_batches():
            try:
                def sync_scrape_post(bot, batch_name, batch_posts, scan_id, site_url, translation_api_key, iab_api_data):
                    with SessionLocal() as batch_db:
                        logger.info(f"Bot {bot.username} processing {batch_name} with {len(batch_posts)} posts")
                        session_cookie = bot.session.split('=')[1] if '=' in bot.session else bot.session
                        
                        for post_link, post_timestamp in batch_posts:
                            full_url = f"{site_url.rstrip('/')}/{post_link.lstrip('/')}"
                            logger.info(f"Bot {bot.username} scraping post {full_url} with timestamp {post_timestamp}")
                            
                            try:
                                # Scrape post details
                                scraped_data_raw = scrape_post_details(
                                    post_link=full_url,
                                    session_cookie=session_cookie,
                                    tor_proxy=bot.tor_proxy,
                                    user_agent=bot.user_agent
                                )
                                if not scraped_data_raw:
                                    logger.error(f"Bot {bot.username} received no data from scrape_post_details for {full_url}")
                                    scan_errors.append(f"No data returned for {full_url}")
                                    continue

                                try:
                                    scraped_data = json.loads(scraped_data_raw)
                                except json.JSONDecodeError as e:
                                    logger.error(f"Bot {bot.username} failed to parse JSON for {full_url}: {str(e)}")
                                    scan_errors.append(f"JSON parse error for {full_url}: {str(e)}")
                                    continue

                                if "error" in scraped_data:
                                    logger.error(f"Error scraping post {full_url}: {scraped_data['error']}")
                                    scan_errors.append(f"Scraping error for {full_url}: {scraped_data['error']}")
                                    continue

                                required_fields = ["title", "content", "author", "timestamp"]
                                if not all(field in scraped_data for field in required_fields):
                                    logger.error(f"Bot {bot.username} received incomplete data for {full_url}: {scraped_data}")
                                    scan_errors.append(f"Incomplete data for {full_url}: missing fields")
                                    continue

                                # Verify timestamp consistency
                                if scraped_data["timestamp"] != post_timestamp:
                                    logger.warning(f"Bot {bot.username} timestamp mismatch for {full_url}: expected {post_timestamp}, got {scraped_data['timestamp']}")
                                    scan_errors.append(f"Timestamp mismatch for {full_url}: expected {post_timestamp}, got {scraped_data['timestamp']}")
                                    continue

                                # Normalize title for safety
                                scraped_data["title"] = unicodedata.normalize('NFKC', scraped_data["title"]).encode('ascii', 'ignore').decode('ascii')
                                scraped_data["content"] = unicodedata.normalize('NFKC', scraped_data["content"]).encode('ascii', 'ignore').decode('ascii')

                                # Detect language of title and content
                                try:
                                    title_lang = detect(scraped_data["title"]) if scraped_data["title"].strip() else 'en'
                                    content_lang = detect(scraped_data["content"]) if scraped_data["content"].strip() else 'en'
                                    logger.info(f"Bot {bot.username} detected languages for {full_url}: title={title_lang}, content={content_lang}")
                                except Exception as e:
                                    logger.warning(f"Bot {bot.username} language detection failed for {full_url}: {str(e)}. Defaulting to translation.")
                                    title_lang = content_lang = 'unknown'  # Force translation if detection fails

                                # Skip translation if both title and content are English
                                if title_lang == 'en' and content_lang == 'en':
                                    logger.info(f"Bot {bot.username} skipping translation for {full_url}: both title and content are English")
                                    title_trans = {
                                        "original": {"text": scraped_data["title"], "language": "en"},
                                        "translated": {"text": scraped_data["title"], "language": "en", "translated": False}
                                    }
                                    content_trans = {
                                        "original": {"text": scraped_data["content"], "language": "en"},
                                        "translated": {"text": scraped_data["content"], "language": "en", "translated": False}
                                    }
                                else:
                                    # Translate title to English
                                    title_trans_raw = translate_string(
                                        scraped_data["title"],
                                        auth_key=translation_api_key,
                                        target_lang="EN"  # Explicitly target English
                                    )
                                    try:
                                        title_trans = json.loads(title_trans_raw)
                                    except json.JSONDecodeError as e:
                                        logger.error(f"Bot {bot.username} failed to parse translation JSON for {full_url} (title): {str(e)}")
                                        scan_errors.append(f"Translation JSON error for {full_url} (title): {str(e)}")
                                        continue

                                    # Translate content to English
                                    content_trans_raw = translate_string(
                                        scraped_data["content"],
                                        auth_key=translation_api_key,
                                        target_lang="EN"  # Explicitly target English
                                    )
                                    try:
                                        content_trans = json.loads(content_trans_raw)
                                    except json.JSONDecodeError as e:
                                        logger.error(f"Bot {bot.username} failed to parse translation JSON for {full_url} (content): {str(e)}")
                                        scan_errors.append(f"Translation JSON error for {full_url} (content): {str(e)}")
                                        continue

                                # Prepare prompt for IAB classification
                                iab_prompt = iab_api_data["prompt"].replace(
                                    "TARGET-POST-PLACEHOLDER",
                                    content_trans["translated"]["text"] or content_trans["original"]["text"]
                                )

                                # Classify post
                                iab_result_raw = iab_classify(
                                    api_key=iab_api_data["api_key"],
                                    model_name=iab_api_data["model"],
                                    prompt=iab_prompt,
                                    max_tokens=iab_api_data["max_tokens"]
                                )
                                try:
                                    iab_result = json.loads(iab_result_raw)
                                except json.JSONDecodeError as e:
                                    logger.error(f"Bot {bot.username} failed to parse IAB JSON for {full_url}: {str(e)}")
                                    scan_errors.append(f"IAB JSON error for {full_url}: {str(e)}")
                                    continue

                                # Check for existing post details
                                existing_post = batch_db.query(MarketplacePostDetails).filter(
                                    MarketplacePostDetails.scan_id == scan_id,
                                    MarketplacePostDetails.timestamp == scraped_data["timestamp"],
                                    MarketplacePostDetails.batch_name == batch_name
                                ).first()

                                if existing_post:
                                    logger.info(f"Bot {bot.username} skipping duplicate post details for {full_url}")
                                    continue

                                db_post_details = MarketplacePostDetails(
                                    scan_id=scan_id,
                                    batch_name=batch_name,
                                    title=scraped_data["title"],
                                    content=scraped_data["content"],
                                    timestamp=scraped_data["timestamp"],
                                    author=scraped_data["author"],
                                    link=full_url,
                                    original_language=content_trans["original"]["language"],
                                    original_text=content_trans["original"]["text"],
                                    translated_language=content_trans["translated"]["language"],
                                    translated_text=content_trans["translated"]["text"],
                                    is_translated=content_trans["translated"]["translated"],
                                    classification=iab_result.get("classification"),
                                    sentiment=iab_result.get("sentiment"),
                                    positive_score=iab_result.get("scores", {}).get("positive"),
                                    negative_score=iab_result.get("scores", {}).get("negative"),
                                    neutral_score=iab_result.get("scores", {}).get("neutral")
                                )
                                batch_db.add(db_post_details)
                                batch_db.commit()
                                logger.info(f"Bot {bot.username} saved post details for {full_url}")

                            except Exception as e:
                                logger.error(f"Bot {bot.username} failed processing post {full_url}: {str(e)}")
                                scan_errors.append(f"Processing error for {full_url}: {str(e)}")
                                batch_db.rollback()
                                continue

                # Assign batches to bots
                with ThreadPoolExecutor(max_workers=len(active_bots)) as executor:
                    tasks = []
                    for i, (batch_name, batch_posts) in enumerate(batches):
                        bot = active_bots[i % len(active_bots)]  # Cycle through bots
                        logger.info(f"Assigning {batch_name} to bot {bot.username}")
                        task = asyncio.get_event_loop().run_in_executor(
                            executor,
                            functools.partial(
                                sync_scrape_post,
                                bot,
                                batch_name,
                                batch_posts,
                                scan_id,
                                site_url,
                                translation_api_key,
                                iab_api_data
                            )
                        )
                        tasks.append(task)

                    # Run all tasks concurrently and wait for completion
                    if tasks:
                        results = await asyncio.gather(*tasks, return_exceptions=True)
                        for i, result in enumerate(results):
                            if isinstance(result, Exception):
                                logger.error(f"Batch {batches[i][0]} failed with exception: {str(result)}")
                                scan_errors.append(f"Batch {batches[i][0]} failed: {str(result)}")

                # Check for errors and set scan status
                with SessionLocal() as final_db:
                    db_scan_final = final_db.query(PostDetailScan).filter(PostDetailScan.id == scan_id).first()
                    if scan_errors:
                        db_scan_final.status = ScanStatus.STOPPED
                        db_scan_final.completion_date = datetime.utcnow()
                        final_db.commit()
                        logger.error(f"Post detail scan {db_scan_final.scan_name} failed with {len(scan_errors)} errors: {'; '.join(scan_errors)}")
                        request.session["messages"] = [{"text": f"Scan {db_scan_final.scan_name} failed with {len(scan_errors)} errors", "category": "error"}]
                    else:
                        db_scan_final.status = ScanStatus.COMPLETED
                        db_scan_final.completion_date = datetime.utcnow()
                        final_db.commit()
                        logger.info(f"Post detail scan {db_scan_final.scan_name} completed")

            except Exception as e:
                logger.error(f"Error in scan {db_scan.scan_name}: {str(e)}")
                with SessionLocal() as error_db:
                    db_scan_error = error_db.query(PostDetailScan).filter(PostDetailScan.id == scan_id).first()
                    db_scan_error.status = ScanStatus.STOPPED
                    db_scan_error.completion_date = datetime.utcnow()
                    error_db.commit()
                    request.session["messages"] = [{"text": f"Scan {db_scan_error.scan_name} failed: {str(e)}", "category": "error"}]

        # Start the scraping task
        asyncio.create_task(scrape_post_batches())

        request.session["messages"] = [{"text": f"Post detail scan {db_scan.scan_name} started", "category": "success"}]
        return JSONResponse(
            content={"message": "Post detail scan started", "flash": {"text": f"Post detail scan {db_scan.scan_name} started", "category": "success"}},
            status_code=200
        )
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error starting post detail scan ID {scan_id}: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


# Delete a post detail scan
@posts_api_router.delete("/{scan_id}")
async def delete_post_scan(scan_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        db_scan = db.query(PostDetailScan).filter(PostDetailScan.id == scan_id).first()
        if not db_scan:
            request.session["messages"] = [{"text": "Post detail scan not found", "category": "error"}]
            logger.warning(f"Post detail scan ID {scan_id} not found")
            raise HTTPException(status_code=404, detail="Post detail scan not found")

        db.delete(db_scan)
        db.commit()
        logger.info(f"Post detail scan {db_scan.scan_name} (ID: {scan_id}) deleted")

        request.session["messages"] = [{"text": f"Post detail scan {db_scan.scan_name} deleted successfully", "category": "success"}]
        return JSONResponse(
            content={"message": "Post detail scan deleted", "flash": {"text": f"Post detail scan {db_scan.scan_name} deleted successfully", "category": "success"}},
            status_code=200
        )
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error deleting post detail scan ID {scan_id}: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


# Get scan results
@posts_api_router.get("/{scan_id}/results")
async def get_scan_results(scan_id: int, db: Session = Depends(get_db)):
    try:
        results = db.query(MarketplacePostDetails).filter(MarketplacePostDetails.scan_id == scan_id).all()
        response_data = [
            {
                "id": result.id,
                "batch_name": result.batch_name,
                "title": result.title,
                "content": result.content,
                "timestamp": result.timestamp,
                "author": result.author,
                "link": result.link,
                "original_language": result.original_language,
                "translated_language": result.translated_language,
                "original_text": result.original_text,
                "translated_text": result.translated_text,
                "is_translated": result.is_translated,
                "classification": result.classification,
                "sentiment": result.sentiment,
                "positive_score": result.positive_score,
                "negative_score": result.negative_score,
                "neutral_score": result.neutral_score,
                "timestamp_added": result.timestamp_added.isoformat()
            } for result in results
        ]
        return JSONResponse(content=response_data, status_code=200)
    except Exception as e:
        logger.error(f"Error fetching results for scan ID {scan_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@posts_api_router.post("/{scan_id}/download")
async def download_post_results(scan_id: int, request: PostDownloadRequest, db: Session = Depends(get_db)):
    try:
        # Verify scan exists
        db_scan = db.query(PostDetailScan).filter(PostDetailScan.id == scan_id).first()
        if not db_scan:
            logger.warning(f"Post detail scan ID {scan_id} not found")
            raise HTTPException(status_code=404, detail="Post detail scan not found")

        # Query selected posts
        results = db.query(MarketplacePostDetails).filter(
            MarketplacePostDetails.scan_id == scan_id,
            MarketplacePostDetails.id.in_(request.post_ids)
        ).all()

        if not results:
            logger.warning(f"No posts found for scan ID {scan_id} with provided post IDs")
            raise HTTPException(status_code=404, detail="No posts found for the provided IDs")

        # Format results as JSON
        response_data = [
            {
                "batch_name": result.batch_name,
                "title": result.title,
                "timestamp": result.timestamp,
                "author": result.author,
                "positive_score": result.positive_score,
                "negative_score": result.negative_score,
                "neutral_score": result.neutral_score,
                "original_language": result.original_language or "-",
                "is_translated": result.is_translated,
                "link": result.link,
                "original_text": result.original_text or "",
                "translated_text": result.translated_text or ""
            } for result in results
        ]

        logger.info(f"Downloaded {len(response_data)} posts for scan ID {scan_id}")
        return JSONResponse(content=response_data, status_code=200)

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error downloading posts for scan ID {scan_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
