import aiosqlite
import os
import logging

logger = logging.getLogger(__name__)

DB_PATH = "data/toptema.db"

async def init_db():
    """
    데이터베이스 및 테이블을 초기화합니다.
    """
    os.makedirs("data", exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        # 테마 일별 스냅샷 테이블
        await db.execute("""
            CREATE TABLE IF NOT EXISTS daily_themes (
                log_date TEXT NOT NULL,
                theme_cd TEXT NOT NULL,
                theme_nm TEXT NOT NULL,
                flu_rt REAL,
                stk_num INTEGER,
                main_stk_nm TEXT,
                PRIMARY KEY (log_date, theme_cd)
            )
        """)
        
        # 테마별 종목 일별 스냅샷 테이블
        await db.execute("""
            CREATE TABLE IF NOT EXISTS daily_theme_stocks (
                log_date TEXT NOT NULL,
                theme_cd TEXT NOT NULL,
                stk_cd TEXT NOT NULL,
                stk_nm TEXT NOT NULL,
                flu_rt REAL,
                rank INTEGER,
                PRIMARY KEY (log_date, theme_cd, stk_cd)
            )
        """)
        await db.commit()
    logger.info("Database initialized successfully.")

async def get_db():
    return await aiosqlite.connect(DB_PATH)
