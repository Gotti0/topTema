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

            theme_results = []
            for t in themes_n:
                cd = t['thema_grp_cd']
                nm = t['thema_nm']
                stk_num = int(t['stk_num'])
                main_stk = t['main_stk']
                
                if is_today:
                    daily_rt = float(t['flu_rt'].replace("+", ""))
                else:
                    # n일 당일 수익률 = (1 + Rn) / (1 + Rn+1) - 1
                    r_n = float(t['dt_prft_rt'].replace("+", "")) / 100
                    if cd in themes_n_plus_1:
                        r_n_plus_1 = float(themes_n_plus_1[cd]['dt_prft_rt'].replace("+", "")) / 100
                        daily_rt = ((1 + r_n) / (1 + r_n_plus_1) - 1) * 100
                    else:
                        daily_rt = 0.0
                
                theme_results.append({
                    "cd": cd, "nm": nm, "rt": round(daily_rt, 2), 
                    "stk_num": stk_num, "main_stk": main_stk
                })

            # 등락률 기준 정렬 (상위 테마 선정용)
            theme_results.sort(key=lambda x: x['rt'], reverse=True)

            async with await get_db() as db:
                for tr in theme_results:
                    await db.execute("""
                        INSERT OR REPLACE INTO daily_themes 
                        (log_date, theme_cd, theme_nm, flu_rt, stk_num, main_stk_nm)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (target_date, tr['cd'], tr['nm'], tr['rt'], tr['stk_num'], tr['main_stk']))
                
                # 상위 30개 테마에 대해서만 종목 상세 정보 수집
                for tr in theme_results[:30]:
                    t_cd = tr['cd']
                    stock_res = await self.client.get_theme_details(theme_grp_cd=t_cd, date_tp=str(date_tp))
                    stocks = stock_res.get("thema_comp_stk", [])
                    
                    # 해당 날짜의 종목별 등락률 정렬
                    sorted_stocks = sorted(
                        stocks, 
                        key=lambda x: float(x.get("flu_rt", "0").replace("+", "")), 
                        reverse=True
                    )

                    for idx, s in enumerate(sorted_stocks[:10]):
                        await db.execute("""
                            INSERT OR REPLACE INTO daily_theme_stocks
                            (log_date, theme_cd, stk_cd, stk_nm, flu_rt, rank)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            target_date, t_cd, s.get("stk_cd").split("_")[0], 
                            s.get("stk_nm"), float(s.get("flu_rt", "0").replace("+", "")), idx + 1
                        ))
                
                await db.commit()
            return True
        except Exception as e:
            logger.error(f"Error collecting snapshot for {target_date}: {e}")
            return False

    async def collect_daily_snapshot(self):
        from datetime import datetime
        today = datetime.now().strftime("%Y%m%d")
        return await self.collect_snapshot(1, today, is_today=True)
