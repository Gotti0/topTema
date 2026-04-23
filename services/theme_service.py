import logging
import time
import aiosqlite
from typing import List, Dict, Any, Optional
from core.client import KiwoomRestClient
from core.database import DB_PATH
from config.settings import ACCOUNTS, get_api_keys

logger = logging.getLogger(__name__)

class ThemeService:
    def __init__(self, client: KiwoomRestClient):
        self.client = client
        self._cache = {}
        self._cache_ttl = 60  # 1 minute cache

    async def get_heatmap_data(self) -> List[Dict[str, Any]]:
        """
        테마별 등락율 데이터를 수집하여 히트맵 형식으로 변환합니다.
        """
        cache_key = "heatmap_all"
        now = time.time()
        
        if cache_key in self._cache:
            data, timestamp = self._cache[cache_key]
            if now - timestamp < self._cache_ttl:
                return data

        try:
            # ka90001 호출
            response = await self.client.get_theme_groups(qry_tp="0", date_tp="1", flu_pl_amt_tp="3")
            theme_list = response.get("thema_grp", [])
            
            # 히트맵 데이터 가공
            processed_data = []
            for item in theme_list:
                processed_data.append({
                    "id": item.get("thema_grp_cd"),
                    "name": item.get("thema_nm"),
                    "value": float(item.get("flu_rt", "0").replace("+", "")),
                    "stk_num": item.get("stk_num"),
                    "main_stk": item.get("main_stk")
                })
            
            self._cache[cache_key] = (processed_data, now)
            return processed_data
        except Exception as e:
            logger.error(f"Error fetching heatmap data: {e}")
            return []

    async def get_theme_top10(self, theme_grp_cd: str, log_date: str = None) -> List[Dict[str, Any]]:
        """
        특정 테마 내 상위 등락율 종목 10개를 가져옵니다.
        log_date가 있으면 해당 시점의 데이터를 실시간 역산하여 가져옵니다.
        """
        now = time.time()

        # 1. 날짜 구분(date_tp) 결정
        if not log_date:
            date_tp = 1
            cache_key = f"top10_{theme_grp_cd}_live"
        else:
            # log_date (YYYYMMDD)가 오늘로부터 몇 영업일 전인지 계산
            try:
                business_dates = await self._get_business_dates()
                if log_date not in business_dates:
                    # 영업일 리스트에 없으면 가장 가까운 과거 영업일 찾기
                    available_dates = [d for d in business_dates if d <= log_date]
                    if not available_dates: return []
                    log_date = available_dates[0]

                # 인덱스를 통해 n거래일 전(date_tp) 계산
                date_tp = business_dates.index(log_date) + 1
                if date_tp > 98: # API 제한 (최대 99일, 역산 위해 n+1 필요하므로 98)
                    logger.warning(f"Requested date {log_date} is too far (date_tp={date_tp})")
                    return []
                cache_key = f"top10_{theme_grp_cd}_{log_date}"
            except Exception as e:
                logger.error(f"Error calculating date_tp for {log_date}: {e}")
                return []

        # 2. 캐시 확인
        if cache_key in self._cache:
            data, timestamp = self._cache[cache_key]
            if now - timestamp < self._cache_ttl:
                return data

        try:
            # 3. API 호출 및 역산 로직
            # n일 전 누적과 n+1일 전 누적을 모두 가져와서 당일 수익률 계산
            stock_res_n = await self.client.get_theme_details(theme_grp_cd=theme_grp_cd, date_tp=str(date_tp))
            stocks_n = {s['stk_cd']: s for s in stock_res_n.get("thema_comp_stk", [])}

            if date_tp == 1:
                # 당일 데이터
                calculated_stocks = []
                for s_cd, s_data in stocks_n.items():
                    calculated_stocks.append({
                        "code": s_cd.split("_")[0],
                        "name": s_data.get("stk_nm"),
                        "price": s_data.get("cur_prc"),
                        "change_rt": s_data.get("flu_rt"),
                        "change_amt": s_data.get("pred_pre"),
                        "raw_rt": float(s_data.get("flu_rt", "0").replace("+", ""))
                    })
            else:
                # 과거 데이터 역산
                stock_res_n1 = await self.client.get_theme_details(theme_grp_cd=theme_grp_cd, date_tp=str(date_tp + 1))
                stocks_n1 = {s['stk_cd']: s for s in stock_res_n1.get("thema_comp_stk", [])}

                calculated_stocks = []
                for s_cd, s_n in stocks_n.items():
                    if s_cd in stocks_n1:
                        r_n = float(s_n.get("flu_rt", "0").replace("+", "")) / 100
                        r_n1 = float(stocks_n1[s_cd].get("flu_rt", "0").replace("+", "")) / 100
                        # 공식: (1 + R_{n+1}) / (1 + R_n) - 1
                        d_rt = ((1 + r_n1) / (1 + r_n) - 1) * 100
                        calculated_stocks.append({
                            "code": s_cd.split("_")[0],
                            "name": s_n.get("stk_nm"),
                            "price": "N/A",
                            "change_rt": f"{'+' if d_rt > 0 else ''}{round(d_rt, 2)}%",
                            "change_amt": "0",
                            "raw_rt": d_rt
                        })

            # 4. 정렬 및 상위 10개 추출
            sorted_stocks = sorted(calculated_stocks, key=lambda x: x['raw_rt'], reverse=True)
            top10 = sorted_stocks[:10]

            # 가공 데이터에서 내부용 정렬 필드 제거
            for s in top10: s.pop("raw_rt")

            self._cache[cache_key] = (top10, now)
            return top10

        except Exception as e:
            logger.error(f"Error fetching real-time theme top 10 for {theme_grp_cd}: {e}")
            return []

    async def _get_business_dates(self) -> List[str]:
        """최신 영업일 리스트를 가져와 캐싱합니다."""
        cache_key = "business_dates"
        if cache_key in self._cache:
            dates, ts = self._cache[cache_key]
            if time.time() - ts < 3600: # 1시간 캐시
                return dates

        try:
            today = datetime.now().strftime("%Y%m%d")
            # 삼성전자 차트로 영업일 기준점 확보
            res = await self.client.get_daily_chart_data(stk_cd="005930", base_dt=today, upd_stkpc_tp="1")
            dates = [item['dt'] for item in res.get("stk_dt_pole_chart_qry", [])]
            self._cache[cache_key] = (dates, time.time())
            return dates
        except Exception as e:
            logger.error(f"Failed to fetch business dates: {e}")
            return []
    async def get_available_dates(self) -> List[str]:
        """
        데이터가 존재하는 날짜 목록을 최신순으로 가져옵니다.
        """
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT DISTINCT log_date FROM daily_themes ORDER BY log_date DESC") as cursor:
                    rows = await cursor.fetchall()
                    return [row[0] for row in rows]
        except Exception as e:
            logger.error(f"Error getting available dates: {e}")
            return []

    async def get_historical_heatmap(self, log_date: str) -> List[Dict[str, Any]]:
        """
        특정 날짜의 테마 데이터를 DB에서 조회합니다.
        """
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("""
                    SELECT theme_cd, theme_nm, flu_rt, stk_num, main_stk_nm 
                    FROM daily_themes 
                    WHERE log_date = ?
                    ORDER BY flu_rt DESC
                """, (log_date,)) as cursor:
                    rows = await cursor.fetchall()
                    return [{
                        "id": r[0], "name": r[1], "value": r[2], 
                        "stk_num": r[3], "main_stk": r[4]
                    } for r in rows]
        except Exception as e:
            logger.error(f"Error getting historical heatmap for {log_date}: {e}")
            return []
