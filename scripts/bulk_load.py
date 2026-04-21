import asyncio
import logging
import sys
import os
import aiosqlite
from datetime import datetime

# 프로젝트 루트를 path에 추가하여 core, config 임포트 가능하게 설정
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.client import KiwoomRestClient
from core.database import init_db, get_db
from config.settings import ACCOUNTS, get_api_keys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BulkLoader")

async def get_business_dates(client: KiwoomRestClient):
    """
    최근 100영업일의 날짜 리스트를 가져옵니다.
    """
    logger.info("영업일 리스트 조회 중...")
    today = datetime.now().strftime("%Y%m%d")
    res = await client.get_daily_chart_data(stk_cd="005930", base_dt=today, upd_stkpc_tp="1")
    # 모의투자 API 응답 키: stk_dt_pole_chart_qry
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
        
        # history[n] = { theme_cd: {name, cum_rt, stk_num, main_stk} }
        history = {}
        
        logger.info("100일치 누적 수익률 데이터 수집 시작 (잠시 시간이 걸립니다)...")
        for n in range(1, 102): # n+1 계산을 위해 101까지 수집
            sys.stdout.write(f"\rAPI 요청 중: date_tp={n}/101")
            sys.stdout.flush()
            try:
                res = await client.get_theme_groups(qry_tp="0", date_tp=str(n), flu_pl_amt_tp="3")
                themes = res.get("thema_grp", [])
                day_data = {}
                for t in themes:
                    cd = t['thema_grp_cd']
                    # "+" 제거 및 float 변환
                    cum_rt = float(t['dt_prft_rt'].replace("+", ""))
                    day_data[cd] = {
                        "name": t['thema_nm'],
                        "cum_rt": cum_rt,
                        "stk_num": int(t['stk_num']),
                        "main_stk": t['main_stk']
                    }
                history[n] = day_data
                await asyncio.sleep(0.1) # 과도한 요청 방지
            except Exception as e:
                logger.error(f"\nError at date_tp={n}: {e}")
                break
        
        print("\n")
        logger.info("일별 등락률 역산 및 DB 저장 시작...")
        
        # get_db() 대신 직접 연결하여 컨텍스트 매니저 사용 (에러 방지)
        from core.database import DB_PATH
        async with aiosqlite.connect(DB_PATH) as db:
            # dates[0]은 오늘, dates[1]은 어제...
            for i in range(100):
                if i >= len(dates): break
                
                log_date = dates[i]
                n = i + 1 # date_tp는 1부터 시작
                
                # 오늘(i=0)의 등락률은 R1 그대로 사용
                # 그 외 과거(i>0)는 (1+R_{n+1})/(1+R_n) - 1 공식 사용
                curr_history = history.get(n)
                next_history = history.get(n+1)
                
                if not curr_history: continue
                
                for cd, data in curr_history.items():
                    if i == 0:
                        daily_rt = data['cum_rt']
                    else:
                        if next_history and cd in next_history:
                            r_n = data['cum_rt'] / 100
                            r_n_plus_1 = next_history[cd]['cum_rt'] / 100
                            # 역산 공식 적용
                            daily_rt = ((1 + r_n_plus_1) / (1 + r_n) - 1) * 100
                        else:
                            # 과거 데이터가 없는 경우 (신규 생성 테마 등)
                            daily_rt = 0.0
                    
                    await db.execute("""
                        INSERT OR REPLACE INTO daily_themes 
                        (log_date, theme_cd, theme_nm, flu_rt, stk_num, main_stk_nm)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (log_date, cd, data['name'], round(daily_rt, 2), data['stk_num'], data['main_stk']))
            
            await db.commit()
        logger.info(f"일괄 적재 완료! ({len(dates)}일치 데이터)")

if __name__ == "__main__":
    asyncio.run(run_bulk_load())
