# core/constants.py

# FID Mappings for Real-time Data (Type 0B: 주식체결)
FID_0B = {
    "20": "time",            # 체결시간
    "10": "curr_price",      # 현재가
    "11": "diff",            # 전일대비
    "12": "rate",            # 등락율
    "27": "offer_price1",    # 최우선 매도호가
    "28": "bid_price1",      # 최우선 매수호가
    "15": "volume",          # 거래량 (+매수, -매도)
    "13": "acc_volume",      # 누적거래량
    "14": "acc_amount",      # 누적거래대금
    "16": "open",            # 시가
    "17": "high",            # 고가
    "18": "low",             # 저가
    "228": "strength",       # 체결강도
    "290": "market_status",  # 장구분 (1:장전, 2:장중, 3:장후)
}

# FID Mappings for Real-time Data (Type 0C: 주식우선호가)
FID_0C = {
    "27": "offer_price1",    # 매도호가1
    "28": "bid_price1",      # 매수호가1
    "10": "curr_price",      # 현재가
}

# FID Mappings for Real-time Data (Type 00: 주문체결)
# Note: Based on Kiwoom API W docs p.467
FID_00 = {
    "9201": "account_no",    # 계좌번호
    "9203": "ord_no",         # 주문번호
    "9205": "mgmt_no",       # 관리번호
    "9001": "stk_cd",        # 종목코드
    "913": "ord_status",     # 주문상태 (접수, 체결, 취소 등)
    "900": "ord_nm",         # 종목명
    "901": "ord_tp",         # 주문구분 (매수, 매도)
    "902": "ord_tp_ext",     # 주문종류 (시장가, 지정가)
    "903": "ord_qty",        # 주문수량
    "904": "ord_price",      # 주문가격
    "905": "unfilled_qty",   # 미체결수량
    "906": "total_filled_qty", # 누적체결수량
    "907": "orig_ord_no",    # 원주문번호
    "908": "ord_media",      # 주문매체
    "910": "filled_price",   # 체결가격
    "911": "filled_qty",     # 체결량
    "912": "filled_time",    # 체결시간
}

# FID Mappings for Real-time Data (Type 04: 잔고)
# Note: Based on Kiwoom API W docs p.471
FID_04 = {
    "9201": "account_no",
    "9001": "stk_cd",
    "900": "stk_nm",
    "930": "hold_qty",       # 보유수량
    "931": "buy_price",      # 매입단가
    "932": "total_buy_amt",  # 총매입금액
    "933": "available_qty",  # 주문가능수량
    "945": "loan_tp",        # 신용구분
    "946": "loan_dt",        # 대출일
    "10": "curr_price",      # 현재가
}
