import logging
from datetime import datetime
from core.client import KiwoomRestClient
from core.database import get_db

logger = logging.getLogger(__name__)

class CollectorService:
    def __init__(self, client: KiwoomRestClient):
        self.client = client

    async def collect_snapshot(self, date_tp: int, target_date: str, is_today: bool = False):
        """
        특정 시점(date_tp)의 데이터를 수집하여 저장합니다.
        """
        try:
            # 1. n일 전 누적 데이터 수집 (R_n)
            res_n = await self.client.get_theme_groups(qry_tp="0", date_tp=str(date_tp), flu_pl_amt_tp="3")
            themes_n = res_n.get("thema_grp", [])
            
            # 2. n+1일 전 누적 데이터 수집 (R_{n+1}) - 역산을 위해 필요
            res_n_plus_1 = await self.client.get_theme_groups(qry_tp="0", date_tp=str(date_tp + 1), flu_pl_amt_tp="3")
            themes_n_plus_1 = {t['thema_grp_cd']: t for t in res_n_plus_1.get("thema_grp", [])}

            async with await get_db() as db:
                for t in themes_n:
                    cd = t['thema_grp_cd']
                    nm = t['thema_nm']
                    stk_num = int(t['stk_num'])
                    main_stk = t['main_stk']
                    
                    # 오늘 데이터면 실시간 등락률 그대로 사용, 과거면 역산 공식 적용
                    if is_today:
                        daily_rt = float(t['flu_rt'].replace("+", ""))
                    else:
                        r_n = float(t['dt_prft_rt'].replace("+", "")) / 100
                        if cd in themes_n_plus_1:
                            r_n_plus_1 = float(themes_n_plus_1[cd]['dt_prft_rt'].replace("+", "")) / 100
                            daily_rt = ((1 + r_n_plus_1) / (1 + r_n) - 1) * 100
                        else:
                            daily_rt = 0.0

                    await db.execute("""
                        INSERT OR REPLACE INTO daily_themes 
                        (log_date, theme_cd, theme_nm, flu_rt, stk_num, main_stk_nm)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (target_date, cd, nm, round(daily_rt, 2), stk_num, main_stk))
                
                await db.commit()
            return True
        except Exception as e:
            logger.error(f"Error collecting snapshot for {target_date}: {e}")
            return False

    async def collect_daily_snapshot(self):
        """
        기존 호출 방식 유지 (오늘 데이터 수집)
        """
        from datetime import datetime
        today = datetime.now().strftime("%Y%m%d")
        return await self.collect_snapshot(1, today, is_today=True)
