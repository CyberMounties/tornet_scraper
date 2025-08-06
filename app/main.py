# app/main.py
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
import os
from app.routes.proxy_gen import proxy_gen_router
from app.database.db import get_db, init_db
from app.database.models import Proxy, APIs, OnionUrl, BotProfile, MarketplacePaginationScan, MarketplacePostScan, Watchlist, WatchlistProfileScan
from app.routes.manage_api import manage_api_router
from app.routes.bot_profile import bot_profile_router
from app.routes.marketplace import marketplace_api_router
from app.routes.posts import posts_api_router
from app.routes.watchlist import watchlist_api_router


app = FastAPI()

app.add_middleware(SessionMiddleware, secret_key="your-secret-key")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(BASE_DIR, "app", "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


init_db()


@app.get("/")
async def dashboard(request: Request, db: Session = Depends(get_db)):
    messages = request.session.pop("messages", [])
    return templates.TemplateResponse("dashboard.html", {"request": request, "messages": messages})


@app.get("/proxy-gen")
async def proxy_gen(request: Request, db: Session = Depends(get_db)):
    proxies = db.query(Proxy).all()
    messages = request.session.pop("messages", [])
    return templates.TemplateResponse(
        "proxy_gen.html",
        {
            "request": request,
            "proxies": [
                {
                    "container_name": p.container_name,
                    "container_ip": p.container_ip,
                    "tor_exit_node": p.tor_exit_node,
                    "timestamp": p.timestamp.isoformat(),
                    "running": p.running
                } for p in proxies
            ],
            "messages": messages
        }
    )


@app.get("/manage-api")
async def manage_api(request: Request, db: Session = Depends(get_db)):
    apis = db.query(APIs).all()
    messages = request.session.pop("messages", [])
    return templates.TemplateResponse(
        "manage_api.html",
        {
            "request": request,
            "apis": [
                {
                    "id": a.id,
                    "api_name": a.api_name,
                    "api_provider": a.api_provider,
                    "api_key": a.api_key,
                    "model": a.model,
                    "max_tokens": a.max_tokens,
                    "prompt": a.prompt,
                    "timestamp": a.timestamp.isoformat(),
                    "is_active": a.is_active
                } for a in apis
            ],
            "messages": messages
        }
    )


@app.get("/bot-profile")
async def bot_profile(request: Request, db: Session = Depends(get_db)):
    profiles = db.query(BotProfile).all()
    onion_url = db.query(OnionUrl).order_by(OnionUrl.timestamp.desc()).first()
    messages = request.session.pop("messages", [])
    return templates.TemplateResponse(
        "bot_profile.html",
        {
            "request": request,
            "profiles": [
                {
                    "id": p.id,
                    "username": p.username,
                    "password": "********",
                    "purpose": p.purpose.value,
                    "tor_proxy": p.tor_proxy,
                    "timestamp": p.timestamp.isoformat()
                } for p in profiles
            ],
            "onion_url": onion_url.url if onion_url else None,
            "messages": messages
        }
    )


@app.get("/marketplace-scan")
async def marketplace(request: Request, db: Session = Depends(get_db)):
    messages = request.session.pop("messages", [])
    pagination_scans = db.query(MarketplacePaginationScan).all()
    post_scans = db.query(MarketplacePostScan).all()
    return templates.TemplateResponse(
        "marketplace.html",
        {
            "request": request,
            "messages": messages,
            "pagination_scans": pagination_scans,
            "post_scans": post_scans
        }
    )


@app.get("/posts-scans")
async def posts_scans(request: Request, db: Session = Depends(get_db)):
    messages = request.session.pop("messages", [])
    return templates.TemplateResponse("posts_scans.html", {"request": request, "messages": messages})


@app.get("/posts-scan-result/{scan_id}")
async def posts_scan_result(scan_id: int, request: Request, db: Session = Depends(get_db), name: str = ""):
    messages = request.session.pop("messages", [])
    return templates.TemplateResponse("posts_scan_result.html", {
        "request": request,
        "messages": messages,
        "scan_id": scan_id,
        "scan_name": name
    })


@app.get("/watchlist")
async def watchlist(request: Request, db: Session = Depends(get_db)):
    messages = request.session.pop("messages", [])
    return templates.TemplateResponse("watchlist.html", {"request": request, "messages": messages})


@app.get("/watchlist-profile/{target_id}", response_class=HTMLResponse)
async def watchlist_profile(request: Request, target_id: int, db: Session = Depends(get_db)):
    try:
        watchlist_item = db.query(Watchlist).filter(Watchlist.id == target_id).first()
        if not watchlist_item:
            raise HTTPException(status_code=404, detail="Watchlist item not found")
        
        scans = db.query(WatchlistProfileScan).filter(WatchlistProfileScan.watchlist_id == target_id).order_by(WatchlistProfileScan.scan_timestamp.desc()).all()
        messages = request.session.pop("messages", [])

        return templates.TemplateResponse("watchlist_profile.html", {
            "request": request,
            "messages": messages,
            "watchlist_item": watchlist_item,
            "scans": scans
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


app.include_router(proxy_gen_router)
app.include_router(manage_api_router)
app.include_router(bot_profile_router)
app.include_router(marketplace_api_router)
app.include_router(posts_api_router)
app.include_router(watchlist_api_router)
