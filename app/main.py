import os
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

app = FastAPI(title="TopTema Dashboard")

# 정적 파일 및 템플릿 설정
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# 글로벌 클라이언트 및 서비스
kiwoom_client = None
theme_service = None

@app.on_event("startup")
async def startup_event():
    global kiwoom_client, theme_service
    if not ACCOUNTS:
        logger.error("No account found in settings.")
        return

    account_no = ACCOUNTS[0]
    app_key, secret_key = get_api_keys(account_no)
    
    kiwoom_client = KiwoomRestClient(app_key, secret_key)
    await kiwoom_client.__aenter__()  # 세션 시작
    theme_service = ThemeService(kiwoom_client)
    logger.info("Application started and Kiwoom client initialized.")

@app.on_event("shutdown")
async def shutdown_event():
    if kiwoom_client:
        await kiwoom_client.__aexit__(None, None, None)
    logger.info("Application shutdown and Kiwoom client closed.")

@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/themes")
async def get_themes():
    if not theme_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    data = await theme_service.get_heatmap_data()
    return data

@app.get("/api/themes/{theme_id}/stocks")
async def get_theme_stocks(theme_id: str):
    if not theme_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    data = await theme_service.get_theme_top10(theme_id)
    return data

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
