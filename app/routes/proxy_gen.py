# app/routes/proxy_gen.py
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.database.models import Proxy
from app.database.db import get_db
from datetime import datetime
from app.services.tor_proxy_gen import create_and_start_proxy
from app.services.rm_container import delete_container
from app.services.container_status import container_running


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


proxy_gen_router = APIRouter(prefix="/api/proxy-gen", tags=["API", "Proxy Generator"])


@proxy_gen_router.post("/create")
async def create_proxy(request: Request, db: Session = Depends(get_db)):
    try:
        proxy_data = create_and_start_proxy()
        proxy = Proxy(
            container_name=proxy_data["container_name"],
            container_ip=proxy_data["container_ip"],
            tor_exit_node=proxy_data["tor_exit_node"],
            timestamp=datetime.fromtimestamp(proxy_data["timestamp"]),
            running=True
        )
        db.add(proxy)
        db.commit()
        db.refresh(proxy)
        
        return JSONResponse(
            content={
                "success": True,
                "message": f"Proxy {proxy.container_name} created successfully",
                "proxy": {
                    "container_name": proxy.container_name,
                    "container_ip": proxy.container_ip,
                    "tor_exit_node": proxy.tor_exit_node,
                    "timestamp": proxy.timestamp.isoformat(),
                    "running": proxy.running
                }
            }
        )
    except Exception as e:
        logger.error(f"Error creating proxy: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create proxy: {str(e)}")


@proxy_gen_router.delete("/delete/{container_name}")
async def delete_proxy(container_name: str, request: Request, db: Session = Depends(get_db)):
    try:
        proxy = db.query(Proxy).filter(Proxy.container_name == container_name).first()
        if not proxy:
            if "messages" not in request.session:
                request.session["messages"] = []
            request.session["messages"].append({"category": "error", "text": "Proxy not found"})
            raise HTTPException(status_code=404, detail="Proxy not found")
        
        success = delete_container(container_name)
        
        if success:
            db.delete(proxy)
            db.commit()
            if "messages" not in request.session:
                request.session["messages"] = []
            request.session["messages"].append({"category": "success", "text": f"Proxy {container_name} deleted successfully"})
            return JSONResponse(
                content={
                    "success": True,
                    "message": f"Proxy {container_name} deleted successfully"
                }
            )
        else:
            if "messages" not in request.session:
                request.session["messages"] = []
            request.session["messages"].append({"category": "error", "text": "Failed to delete proxy"})
            raise HTTPException(status_code=500, detail="Failed to delete proxy")
    except Exception as e:
        logger.error(f"Error deleting proxy: {str(e)}")
        if "messages" not in request.session:
            request.session["messages"] = []
        request.session["messages"].append({"category": "error", "text": f"Failed to delete proxy: {str(e)}"})
        raise HTTPException(status_code=500, detail=f"Failed to delete proxy: {str(e)}")


@proxy_gen_router.get("/list")
async def list_proxies(db: Session = Depends(get_db)):
    try:
        proxies = db.query(Proxy).all()
        proxy_list = []
        
        for proxy in proxies:
            running = container_running(proxy.container_name)
            if proxy.running != running:
                proxy.running = running
                db.commit()
            
            proxy_list.append({
                "container_name": proxy.container_name,
                "container_ip": proxy.container_ip,
                "tor_exit_node": proxy.tor_exit_node,
                "timestamp": proxy.timestamp.isoformat(),
                "running": proxy.running
            })
        
        return JSONResponse(content={"proxies": proxy_list})
    except Exception as e:
        logger.error(f"Error listing proxies: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
