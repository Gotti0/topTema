class KiwoomError(Exception):
    """age_ant 프로젝트에서 발생하는 모든 예외의 기본 클래스입니다."""
    def __init__(self, message: str = "An unknown error occurred in Kiwoom API"):
        self.message = message
        super().__init__(self.message)

class KiwoomAPIError(KiwoomError):
    """키움 REST API 호출 중 오류가 발생했을 때 발생하는 예외입니다."""
    def __init__(self, message: str, status_code: int = None, response_body: str = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body

    def __str__(self):
        return f"KiwoomAPIError(status={self.status_code}, message='{self.message}')"

class TokenExpiredError(KiwoomAPIError):
    """OAuth2 접근 토큰이 만료되었을 때 발생하는 예외입니다."""
    def __init__(self, message: str = "Access token has expired", status_code: int = 401):
        super().__init__(message, status_code=status_code)

class RateLimitExceededError(KiwoomAPIError):
    """키움 API의 호출 제한(Rate Limit)을 초과했을 때 발생하는 예외입니다."""
    def __init__(self, message: str = "Rate limit exceeded", status_code: int = 429):
        super().__init__(message, status_code=status_code)

class WebSocketError(KiwoomError):
    """웹소켓 통신 중 발생하는 예외의 기본 클래스입니다."""
    pass

class WebSocketLoginError(WebSocketError):
    """웹소켓 로그인(인증) 실패 시 발생하는 예외입니다."""
    def __init__(self, message: str = "WebSocket login failed"):
        super().__init__(message)

class WebSocketConnectionError(WebSocketError):
    """웹소켓 연결이 끊어지거나 설정에 실패했을 때 발생하는 예외입니다."""
    def __init__(self, message: str = "WebSocket connection error"):
        super().__init__(message)

class StrategyError(KiwoomError):
    """트레이딩 전략 계산이나 상태 전이 중 발생하는 예외입니다."""
    pass
