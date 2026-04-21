import logging
from datetime import datetime
from core.client import KiwoomRestClient
from core.database import get_db

logger = logging.getLogger(__name__)

class CollectorService:
    def __init__(self, client: KiwoomRestClient):
        self.client = client

    async def collect_daily_snapshot(self):
        """
        오늘의 테마 및 대장주 정보를 수집하여 DB에 저장합니다.
        보통 장 마감 후 호출됩니다.
        """
        log_date = datetime.now().strftime("%Y%m%d")
        logger.info(f"Starting daily snapshot collection for {log_date}")

        try:
            # 1. 전체 테마 그룹 수집 (ka90001)
            theme_res = await self.client.get_theme_groups(qry_tp="0", date_tp="1", flu_pl_amt_tp="3")
            theme_list = theme_res.get("thema_grp", [])

            async with await get_db() as db:
                # 테마 정보 저장
                for theme in theme_list:
                    theme_cd = theme.get("thema_grp_cd")
                    theme_nm = theme.get("thema_nm")
                    flu_rt = float(theme.get("flu_rt", "0").replace("+", ""))
                    stk_num = int(theme.get("stk_num", "0"))
                    main_stk = theme.get("main_stk")

                    await db.execute("""
                        INSERT OR REPLACE INTO daily_themes 
                        (log_date, theme_cd, theme_nm, flu_rt, stk_num, main_stk_nm)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (log_date, theme_cd, theme_nm, flu_rt, stk_num, main_stk))

                    # 2. 각 테마의 상위 10개 종목 수집 (ka90002)
                    # *주의: 테마가 많을 경우 API 호출 제한에 걸릴 수 있으므로 
                    # 실제 운영 환경에서는 등락률 상위 N개 테마만 상세 수집하는 것이 안전함.
                    if flu_rt > 0: # 상승한 테마만 우선 수집 예시
                        stock_res = await self.client.get_theme_details(theme_grp_cd=theme_cd, date_tp="1")
                        stocks = stock_res.get("thema_comp_stk", [])
                        
                        # 등락률 순 정렬
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
                                log_date, 
                                theme_cd, 
                                s.get("stk_cd"), 
                                s.get("stk_nm"), 
                                float(s.get("flu_rt", "0").replace("+", "")),
                                idx + 1
                            ))
                
                await db.commit()
                logger.info(f"Daily snapshot for {log_date} completed.")
                return True

        except Exception as e:
            logger.error(f"Error during daily collection: {e}")
            return False
