import asyncio
from config.settings import ACCOUNTS, get_api_keys
from core.client import KiwoomRestClient

async def main():
    if not ACCOUNTS:
        print("No accounts")
        return
    account_no = ACCOUNTS[0]
    app_key, secret_key = get_api_keys(account_no)
    client = KiwoomRestClient(app_key, secret_key)
    async with client:
        res = await client.get_daily_chart_data(stk_cd="005930", base_dt="20260424", upd_stkpc_tp="1")
        items = res.get("stk_dt_pole_chart_qry", [])
        if items:
            print(items[0])
        else:
            print("No items")

if __name__ == "__main__":
    asyncio.run(main())
