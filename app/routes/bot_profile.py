# app/routes/bot_profile.py
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.database.models import BotProfile, OnionUrl, BotPurpose, APIs
from app.database.db import get_db
from typing import Optional
from app.services.tornet_forum_login import login_to_tor_website
from app.services.gen_random_ua import gen_desktop_ua


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


bot_profile_router = APIRouter(prefix="/api/bot-profile", tags=["API", "Bot Profile Management"])


# Pydantic models for validation
class BotProfileCreate(BaseModel):
    username: str
    password: str
    purpose: str
    tor_proxy: Optional[str] = None
    session: Optional[str] = None


class BotProfileUpdate(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    purpose: Optional[str] = None
    tor_proxy: Optional[str] = None
    user_agent: Optional[str] = None
    session: Optional[str] = None


class OnionUrlCreate(BaseModel):
    url: str


# Get all bot profiles
@bot_profile_router.get("/list")
async def get_bot_profiles(db: Session = Depends(get_db)):
    try:
        profiles = db.query(BotProfile).all()
        return [
            {
                "id": p.id,
                "username": p.username,
                "password": "********",
                "actual_password": p.password,
                "purpose": p.purpose.value,
                "tor_proxy": p.tor_proxy,
                "has_session": bool(p.session and len(p.session) > 0),
                "session": p.session,
                "user_agent": p.user_agent,
                "timestamp": p.timestamp.isoformat()
            } for p in profiles
        ]
    except Exception as e:
        logger.error(f"Error fetching bot profiles: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Create a bot profile
@bot_profile_router.post("/create")
async def create_bot_profile(profile: BotProfileCreate, request: Request, db: Session = Depends(get_db)):
    try:
        if db.query(BotProfile).filter(BotProfile.username == profile.username).first():
            request.session["messages"] = [{"text": f"Username {profile.username} already exists", "category": "error"}]
            raise HTTPException(status_code=400, detail="Username already exists")
        
        db_profile = BotProfile(
            username=profile.username,
            password=profile.password,
            purpose=BotPurpose(profile.purpose),
            tor_proxy=profile.tor_proxy,
            session=profile.session,
            user_agent=gen_desktop_ua()
        )
        db.add(db_profile)
        db.commit()
        db.refresh(db_profile)
        request.session["messages"] = [{"text": "Bot profile created successfully", "category": "success"}]
        return {"message": "Bot profile created", "flash": {"text": "Bot profile created successfully", "category": "success"}}
    except Exception as e:
        logger.error(f"Error creating bot profile: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


# Update a bot profile
@bot_profile_router.put("/{profile_id}")
async def update_bot_profile(profile_id: int, profile: BotProfileUpdate, request: Request, db: Session = Depends(get_db)):
    try:
        db_profile = db.query(BotProfile).filter(BotProfile.id == profile_id).first()
        if not db_profile:
            request.session["messages"] = [{"text": "Bot profile not found", "category": "error"}]
            raise HTTPException(status_code=404, detail="Bot profile not found")
        
        if profile.username and profile.username != db_profile.username:
            if db.query(BotProfile).filter(BotProfile.username == profile.username).first():
                request.session["messages"] = [{"text": f"Username {profile.username} already exists", "category": "error"}]
                raise HTTPException(status_code=400, detail="Username already exists")
        
        if profile.username:
            db_profile.username = profile.username
        if profile.password:
            db_profile.password = profile.password
        if profile.purpose:
            db_profile.purpose = BotPurpose(profile.purpose)
        if profile.tor_proxy is not None:
            db_profile.tor_proxy = profile.tor_proxy
        if profile.user_agent:
            db_profile.user_agent = profile.user_agent
        if profile.session is not None:
            db_profile.session = profile.session
        
        db.commit()
        db.refresh(db_profile)
        request.session["messages"] = [{"text": "Bot profile updated successfully", "category": "success"}]
        return {"message": "Bot profile updated", "flash": {"text": "Bot profile updated successfully", "category": "success"}}
    except Exception as e:
        logger.error(f"Error updating bot profile: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


# Delete a bot profile
@bot_profile_router.delete("/{profile_id}")
async def delete_bot_profile(profile_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        db_profile = db.query(BotProfile).filter(BotProfile.id == profile_id).first()
        if not db_profile:
            request.session["messages"] = [{"text": "Bot profile not found", "category": "error"}]
            raise HTTPException(status_code=404, detail="Bot profile not found")
        
        db.delete(db_profile)
        db.commit()
        request.session["messages"] = [{"text": "Bot profile deleted successfully", "category": "success"}]
        return {"message": "Bot profile deleted", "flash": {"text": "Bot profile deleted successfully", "category": "success"}}
    except Exception as e:
        logger.error(f"Error deleting bot profile: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


# Get .onion URL
@bot_profile_router.get("/onion-url")
async def get_onion_url(db: Session = Depends(get_db)):
    try:
        onion_url = db.query(OnionUrl).order_by(OnionUrl.timestamp.desc()).first()
        return {"url": onion_url.url if onion_url else None}
    except Exception as e:
        logger.error(f"Error fetching onion URL: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Set .onion URL
@bot_profile_router.post("/onion-url")
async def set_onion_url(onion: OnionUrlCreate, request: Request, db: Session = Depends(get_db)):
    try:
        db_onion = OnionUrl(url=onion.url)
        db.add(db_onion)
        db.commit()
        db.refresh(db_onion)
        request.session["messages"] = [{"text": ".onion URL updated successfully", "category": "success"}]
        return {"message": ".onion URL updated", "flash": {"text": ".onion URL updated successfully", "category": "success"}}
    except Exception as e:
        logger.error(f"Error setting onion URL: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


# Perform automated login for all bot profiles
@bot_profile_router.post("/perform-login")
async def perform_bot_login(request: Request, db: Session = Depends(get_db)):
    try:
        # Fetch the latest .onion URL
        onion_url = db.query(OnionUrl).order_by(OnionUrl.timestamp.desc()).first()
        if not onion_url:
            request.session["messages"] = [{"text": "No .onion URL set", "category": "error"}]
            raise HTTPException(status_code=400, detail="No .onion URL set")

        # Fetch active CAPTCHA API
        captcha_api = db.query(APIs).filter(APIs.api_type == "captcha_api", APIs.is_active == True).first()
        if not captcha_api:
            request.session["messages"] = [{"text": "No active CAPTCHA API found", "category": "error"}]
            raise HTTPException(status_code=400, detail="No active CAPTCHA API found")

        # Fetch all bot profiles
        profiles = db.query(BotProfile).all()
        if not profiles:
            request.session["messages"] = [{"text": "No bot profiles found", "category": "error"}]
            raise HTTPException(status_code=400, detail="No bot profiles found")

        success_count = 0
        failed_logins = []
        for profile in profiles:
            if not profile.tor_proxy:
                logger.warning(f"Skipping login for {profile.username}: No tor proxy set")
                failed_logins.append(f"{profile.username}: No tor proxy set")
                continue

            login_params = {
                "api_key": captcha_api.api_key,
                "max_tokens": captcha_api.max_tokens,
                "model_name": captcha_api.model,
                "login_url": onion_url.url,
                "username": profile.username,
                "password": profile.password,
                "tor_proxy": profile.tor_proxy,
                "prompt": captcha_api.prompt
            }

            logger.info(f"Attempting login for {profile.username}")
            session = login_to_tor_website(**login_params)
            if session and session.cookies.get("session"):
                session_cookie = f"session={session.cookies.get('session')}"
                profile.session = session_cookie
                db.commit()
                logger.info(f"Login successful for {profile.username}, session saved")
                success_count += 1
            else:
                logger.error(f"Login failed for {profile.username}")
                failed_logins.append(f"{profile.username}: Login failed")

        if success_count > 0:
            message = f"Successfully logged in {success_count} bot profile(s)"
            if failed_logins:
                message += f". Failed logins: {', '.join(failed_logins)}"
            request.session["messages"] = [{"text": message, "category": "success"}]
        else:
            message = f"No successful logins. Failed logins: {', '.join(failed_logins) if failed_logins else 'None'}"
            request.session["messages"] = [{"text": message, "category": "error"}]
        
        return {
            "message": f"Login process completed, {success_count} successful logins",
            "flash": {
                "text": message,
                "category": "success" if success_count > 0 else "error"
            }
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error during automated login: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")
