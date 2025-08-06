# app/routes/manage_api.py
import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.database.models import APIs
from app.database.db import get_db
from datetime import datetime
from pydantic import BaseModel


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


manage_api_router = APIRouter(prefix="/api/manage-api", tags=["API", "API Management"])


# Pydantic models for request validation
class DeepLCreateRequest(BaseModel):
    api_name: str
    api_key: str


class IABCreateRequest(BaseModel):
    api_name: str
    api_key: str
    model: str
    max_tokens: int
    prompt: str


class CaptchaCreateRequest(BaseModel):
    api_name: str
    api_key: str
    model: str
    max_tokens: int
    prompt: str


class UpdateRequest(BaseModel):
    api_name: str
    api_key: str
    model: str | None = None
    max_tokens: int | None = None
    prompt: str | None = None


def set_active_api(db: Session, api_id: int, api_provider: str):
    db.query(APIs).filter(
        APIs.api_provider == api_provider,
        APIs.id != api_id
    ).update({"is_active": False})
    db.query(APIs).filter(APIs.id == api_id).update({"is_active": True})
    db.commit()


# Create DeepL API
@manage_api_router.post("/create/deepl")
async def create_deepl_api(request: DeepLCreateRequest, db: Session = Depends(get_db)):
    try:
        existing_api = db.query(APIs).filter(APIs.api_name == request.api_name).first()
        if existing_api:
            raise HTTPException(status_code=400, detail="API name already exists")
        
        api = APIs(
            api_name=request.api_name,
            api_provider="deepl",
            api_type="translation_api",
            api_key=request.api_key,
            timestamp=datetime.utcnow(),
            is_active=False
        )
        db.add(api)
        db.commit()
        db.refresh(api)
        return JSONResponse(content={"message": "DeepL API created successfully"})
    except Exception as e:
        logger.error(f"Error creating DeepL API: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Create IAB API
@manage_api_router.post("/create/iab")
async def create_iab_api(request: IABCreateRequest, db: Session = Depends(get_db)):
    try:
        existing_api = db.query(APIs).filter(APIs.api_name == request.api_name).first()
        if existing_api:
            raise HTTPException(status_code=400, detail="API name already exists")
        
        api = APIs(
            api_name=request.api_name,
            api_provider="anthropic",
            api_type="iab_api",
            api_key=request.api_key,
            model=request.model,
            max_tokens=request.max_tokens,
            prompt=request.prompt,
            timestamp=datetime.utcnow(),
            is_active=False
        )
        db.add(api)
        db.commit()
        db.refresh(api)
        return JSONResponse(content={"message": "IAB API created successfully"})
    except Exception as e:
        logger.error(f"Error creating IAB API: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Create Captcha API
@manage_api_router.post("/create/captcha")
async def create_captcha_api(request: CaptchaCreateRequest, db: Session = Depends(get_db)):
    try:
        existing_api = db.query(APIs).filter(APIs.api_name == request.api_name).first()
        if existing_api:
            raise HTTPException(status_code=400, detail="API name already exists")
        
        api = APIs(
            api_name=request.api_name,
            api_provider="openai",
            api_type="captcha_api",
            api_key=request.api_key,
            model=request.model,
            max_tokens=request.max_tokens,
            prompt=request.prompt,
            timestamp=datetime.utcnow(),
            is_active=False
        )
        db.add(api)
        db.commit()
        db.refresh(api)
        return JSONResponse(content={"message": "Captcha API created successfully"})
    except Exception as e:
        logger.error(f"Error creating Captcha API: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# List all APIs
@manage_api_router.get("/list")
async def list_apis(db: Session = Depends(get_db)):
    try:
        apis = db.query(APIs).all()
        return {
            "apis": [
                {
                    "id": a.id,
                    "api_name": a.api_name,
                    "api_provider": a.api_provider,
                    "api_type": a.api_type,
                    "api_key": a.api_key,
                    "model": a.model,
                    "max_tokens": a.max_tokens,
                    "prompt": a.prompt,
                    "timestamp": a.timestamp.isoformat(),
                    "is_active": a.is_active
                } for a in apis
            ]
        }
    except Exception as e:
        logger.error(f"Error listing APIs: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Update API
@manage_api_router.put("/update/{api_id}")
async def update_api(api_id: int, request: UpdateRequest, db: Session = Depends(get_db)):
    try:
        api = db.query(APIs).filter(APIs.id == api_id).first()
        if not api:
            raise HTTPException(status_code=404, detail="API not found")
        
        existing_api = db.query(APIs).filter(
            APIs.api_name == request.api_name,
            APIs.id != api_id
        ).first()
        if existing_api:
            raise HTTPException(status_code=400, detail="API name already exists")
        
        api.api_name = request.api_name
        api.api_key = request.api_key
        if request.model is not None:
            api.model = request.model
        if request.max_tokens is not None:
            api.max_tokens = request.max_tokens
        if request.prompt is not None:
            api.prompt = request.prompt
        
        db.commit()
        db.refresh(api)
        return JSONResponse(content={"message": "API updated successfully"})
    except Exception as e:
        logger.error(f"Error updating API: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Delete API
@manage_api_router.delete("/delete/{api_id}")
async def delete_api(api_id: int, db: Session = Depends(get_db)):
    try:
        api = db.query(APIs).filter(APIs.id == api_id).first()
        if not api:
            raise HTTPException(status_code=404, detail="API not found")
        
        db.delete(api)
        db.commit()
        return JSONResponse(content={"message": "API deleted successfully"})
    except Exception as e:
        logger.error(f"Error deleting API: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Activate API
@manage_api_router.post("/activate/{api_id}")
async def activate_api(api_id: int, db: Session = Depends(get_db)):
    try:
        api = db.query(APIs).filter(APIs.id == api_id).first()
        if not api:
            raise HTTPException(status_code=404, detail="API not found")
        
        set_active_api(db, api_id, api.api_provider)
        return JSONResponse(content={"message": f"{api.api_provider} API activated successfully"})
    except Exception as e:
        logger.error(f"Error activating API: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Get a single API by ID
@manage_api_router.get("/get/{api_id}")
async def get_api(api_id: int, db: Session = Depends(get_db)):
    try:
        api = db.query(APIs).filter(APIs.id == api_id).first()
        if not api:
            raise HTTPException(status_code=404, detail="API not found")
        
        return {
            "api": {
                "id": api.id,
                "api_name": api.api_name,
                "api_provider": api.api_provider,
                "api_type": api.api_type,
                "api_key": api.api_key,
                "model": api.model,
                "max_tokens": api.max_tokens,
                "prompt": api.prompt,
                "timestamp": api.timestamp.isoformat(),
                "is_active": api.is_active
            }
        }
    except Exception as e:
        logger.error(f"Error fetching API {api_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
