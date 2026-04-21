import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from core.client import KiwoomRestClient
from services.theme_service import ThemeService
from config.settings import ACCOUNTS, get_api_keys
import uvicorn
import logging

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from core.database import init_db
from services.collector_service import CollectorService

# 글로벌 클라이언트 및 서비스
kiwoom_client = None
theme_service = None
collector_service = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI Lifespan 이벤트 핸들러.
    애플리케이션 시작 시 리소스를 초기화하고, 종료 시 해제합니다.
    """
    global kiwoom_client, theme_service, collector_service
    
    # DB 초기화
    await init_db()
    
    # [Startup]
    if ACCOUNTS:
        account_no = ACCOUNTS[0]
        app_key, secret_key = get_api_keys(account_no)
        
        kiwoom_client = KiwoomRestClient(app_key, secret_key)
        await kiwoom_client.__aenter__()  # 세션 시작
        theme_service = ThemeService(kiwoom_client)
        collector_service = CollectorService(kiwoom_client)
        logger.info("Application started and Kiwoom client/DB initialized.")
        
        # [Auto Collect] 서버 시작 시 자동 수집 실행
        asyncio.create_task(collector_service.collect_daily_snapshot())
        logger.info("Automatic daily snapshot collection triggered.")
    else:
        logger.error("No account found in settings. Client initialization skipped.")

    yield # 애플리케이션 실행 중

    # [Shutdown]
    if kiwoom_client:
        await kiwoom_client.__aexit__(None, None, None)
    logger.info("Application shutdown and Kiwoom client closed.")

app = FastAPI(title="TopTema Dashboard", lifespan=lifespan)

# 정적 파일 및 템플릿 설정
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.post("/api/collect")
async def trigger_collection():
    """
    당일 스냅샷 수집을 수동으로 트리거합니다.
    """
    if not collector_service:
        raise HTTPException(status_code=503, detail="Collector service not initialized")
    success = await collector_service.collect_daily_snapshot()
    if success:
        return {"message": "Daily snapshot collected successfully"}
    else:
        raise HTTPException(status_code=500, detail="Collection failed")

@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/history/dates")
async def get_history_dates():
    if not theme_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return await theme_service.get_available_dates()

@app.get("/api/themes")
async def get_themes(date: str = None):
    if not theme_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    if date:
        return await theme_service.get_historical_heatmap(date)
    
    data = await theme_service.get_heatmap_data()
    return data

@app.get("/api/themes/{theme_id}/stocks")
async def get_theme_stocks(theme_id: str):
    if not theme_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    data = await theme_service.get_theme_top10(theme_id)
    return data

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5173))
    uvicorn.run(app, host="0.0.0.0", port=port)
