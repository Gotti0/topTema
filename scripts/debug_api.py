import asyncio
import logging
import sys
import os
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.client import KiwoomRestClient
from config.settings import ACCOUNTS, get_api_keys

async def debug_chart():
    acc = ACCOUNTS[0]
    app_key, secret_key = get_api_keys(acc)
    async with KiwoomRestClient(app_key, secret_key) as client:
        today = datetime.now().strftime("%Y%m%d")
        print(f"Requesting chart data for 005930, base_dt={today}")
        res = await client.get_daily_chart_data(stk_cd="005930", base_dt=today, upd_stkpc_tp="1")
        print(f"Response keys: {res.keys()}")
        if 'stk_ddwkmm' in res:
            print(f"Data length: {len(res['stk_ddwkmm'])}")
            if len(res['stk_ddwkmm']) > 0:
                print(f"First item: {res['stk_ddwkmm'][0]}")
        else:
            print(f"Full response: {res}")

if __name__ == "__main__":
    asyncio.run(debug_chart())
