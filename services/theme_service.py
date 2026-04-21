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
        log_date가 있으면 DB에서, 없으면 실시간 API로 가져옵니다.
        """
        if log_date:
            try:
                # 과거 데이터는 캐시를 타지 않거나 날짜별 전용 캐시 사용
                cache_key = f"top10_{theme_grp_cd}_{log_date}"
                if cache_key in self._cache:
                    data, timestamp = self._cache[cache_key]
                    if time.time() - timestamp < self._cache_ttl:
                        return data

                async with aiosqlite.connect(DB_PATH) as db:
                    async with db.execute("""
                        SELECT stk_cd, stk_nm, flu_rt 
                        FROM daily_theme_stocks 
                        WHERE theme_cd = ? AND log_date = ?
                        ORDER BY rank ASC
                        LIMIT 10
                    """, (theme_grp_cd, log_date)) as cursor:
                        rows = await cursor.fetchall()
                        res = [{
                            "code": r[0], "name": r[1], "price": "N/A", 
                            "change_rt": f"{'+' if r[2] > 0 else ''}{r[2]}%",
                            "change_amt": "0"
                        } for r in rows]
                        self._cache[cache_key] = (res, time.time())
                        return res
            except Exception as e:
                logger.error(f"Error fetching historical top 10 for {theme_grp_cd}: {e}")
                return []

        # 실시간 데이터용 캐시 키 (기존 유지)
        cache_key = f"top10_{theme_grp_cd}_live"
        now = time.time()
        # ... (생략된 실시간 조회 로직 유지)

        if cache_key in self._cache:
            data, timestamp = self._cache[cache_key]
            if now - timestamp < self._cache_ttl:
                return data

        try:
            # ka90002 호출
            response = await self.client.get_theme_details(theme_grp_cd=theme_grp_cd, date_tp="1")
            stock_list = response.get("thema_comp_stk", [])
            
            # 등락율 기준 정렬 후 상위 10개 추출
            sorted_stocks = sorted(
                stock_list, 
                key=lambda x: float(x.get("flu_rt", "0").replace("+", "")), 
                reverse=True
            )
            
            top10 = []
            for item in sorted_stocks[:10]:
                top10.append({
                    "code": item.get("stk_cd"),
                    "name": item.get("stk_nm"),
                    "price": item.get("cur_prc"),
                    "change_rt": item.get("flu_rt"),
                    "change_amt": item.get("pred_pre")
                })
            
            self._cache[cache_key] = (top10, now)
            return top10
        except Exception as e:
            logger.error(f"Error fetching theme top 10: {e}")
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
