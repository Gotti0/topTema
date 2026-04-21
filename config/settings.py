import os
from dotenv import load_dotenv

load_dotenv()

IS_MOCK = os.getenv("KIWOOM_IS_MOCK", "True").lower() == "true"

API_DOMAIN = "https://mockapi.kiwoom.com" if IS_MOCK else "https://api.kiwoom.com"
WS_DOMAIN = "wss://mockapi.kiwoom.com" if IS_MOCK else "wss://api.kiwoom.com"

# 계좌 목록
ACCOUNTS = os.getenv("KIWOOM_ACCOUNTS", "").split(",")
ACCOUNTS = [acc.strip() for acc in ACCOUNTS if acc.strip()]

def get_api_keys(account_no: str):
    """
    계좌번호에 해당하는 API Key와 Secret Key를 반환합니다.
    """
    prefix = "MOCK" if IS_MOCK else "REAL"
    app_key = os.getenv(f"KIWOOM_{prefix}_APP_KEY_{account_no}")
    secret_key = os.getenv(f"KIWOOM_{prefix}_SECRET_KEY_{account_no}")
    return app_key, secret_key
