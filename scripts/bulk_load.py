import asyncio
import logging
import sys
import os
import aiosqlite
import time
from datetime import datetime

# 프로젝트 루트를 path에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.client import KiwoomRestClient
from core.database import init_db, DB_PATH
from config.settings import ACCOUNTS, get_api_keys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("DeepBulkLoader")

async def get_business_dates(client: KiwoomRestClient):
    logger.info("영업일 리스트 조회 중...")
    today = datetime.now().strftime("%Y%m%d")
    res = await client.get_daily_chart_data(stk_cd="005930", base_dt=today, upd_stkpc_tp="1")
    chart_data = res.get("stk_dt_pole_chart_qry", [])
    return [item['dt'] for item in chart_data]

async def run_bulk_load():
    if not ACCOUNTS:
        logger.error("설정된 계좌가 없습니다.")
        return

    acc = ACCOUNTS[0]
    app_key, secret_key = get_api_keys(acc)
    
    await init_db()
    
    async with KiwoomRestClient(app_key, secret_key) as client:
        dates = await get_business_dates(client)
        if not dates:
            logger.error("영업일 데이터를 가져오지 못했습니다.")
            return
        
        # 1. 누적 수익률 데이터 수집 (101일치)
        history = {}
        logger.info("1. 100일치 테마 누적 수익률 수집 시작...")
        for n in range(1, 102):
            try:
                res = await client.get_theme_groups(qry_tp="0", date_tp=str(n), flu_pl_amt_tp="3")
                themes = res.get("thema_grp", [])
                day_data = {t['thema_grp_cd']: {
                    "name": t['thema_nm'],
                    "cum_rt": float(t['dt_prft_rt'].replace("+", "")),
                    "stk_num": int(t['stk_num']),
                    "main_stk": t['main_stk']
                } for t in themes}
                history[n] = day_data
                if n % 10 == 0: logger.info(f"진행 중: {n}/101일 수집 완료")
                await asyncio.sleep(0.2) 
            except Exception as e:
                logger.error(f"Error at date_tp={n}: {e}")
                break

        # 2. 일별 데이터 역산 및 상세 종목 수집 저장
        logger.info("2. 일별 데이터 역산 및 종목 상세 정보 수집/저장 시작...")
        async with aiosqlite.connect(DB_PATH) as db:
            for i in range(100):
                if i >= len(dates): break
                
                log_date = dates[i]
                n = i + 1
                curr_history = history.get(n)
                next_history = history.get(n+1)
                
                if not curr_history: continue
                
                # 해당 날짜의 테마들 저장
                theme_list_for_stocks = []
                for cd, data in curr_history.items():
                    if i == 0:
                        daily_rt = data['cum_rt']
                    else:
                        if next_history and cd in next_history:
                            r_n = data['cum_rt'] / 100
                            r_n_plus_1 = next_history[cd]['cum_rt'] / 100
                            daily_rt = ((1 + r_n_plus_1) / (1 + r_n) - 1) * 100
                        else:
                            daily_rt = 0.0
                    
                    daily_rt = round(daily_rt, 2)
                    theme_list_for_stocks.append({"cd": cd, "rt": daily_rt})

                    await db.execute("""
                        INSERT OR REPLACE INTO daily_themes 
                        (log_date, theme_cd, theme_nm, flu_rt, stk_num, main_stk_nm)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (log_date, cd, data['name'], daily_rt, data['stk_num'], data['main_stk']))

                await db.commit() # 날짜별로 커밋
                logger.info(f"[{log_date}] 완료 ({i+1}/100)")
                await asyncio.sleep(0.1) # 날짜 간 지연

        logger.info("모든 테마 데이터 적재가 완료되었습니다! (종목 상세는 조회 시 실시간 처리됩니다)")

if __name__ == "__main__":
    asyncio.run(run_bulk_load())
