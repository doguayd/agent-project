import re
from typing import Optional, Dict, Any
from urllib.parse import urlparse
from services.core.logger_service import setup_logger

logger = setup_logger("HttpClientService")

# Allow only localhost and RFC-1918 private addresses
_PRIVATE_HOST = re.compile(
    r"^(localhost"
    r"|127\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|0\.0\.0\.0"
    r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r")$"
)


class HttpClientService:
    """Make HTTP requests to local/private endpoints. Public internet is blocked."""

    def __init__(self, default_timeout: int = 10):
        self.default_timeout = default_timeout
        logger.info(f"HttpClientService initialized | timeout={default_timeout}s")

    def _is_allowed(self, url: str) -> bool:
        host = urlparse(url).hostname or ""
        return bool(_PRIVATE_HOST.match(host))

    async def request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        body: Optional[Any] = None,
        params: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> Dict:
        """
        Perform an HTTP request. Only localhost / private-IP targets are allowed.

        Returns a dict with: status_code, headers, body, latency_ms
        or an 'error' key on failure.
        """
        if not self._is_allowed(url):
            return {
                "error": (
                    f"URL '{url}' is not allowed. "
                    "Only localhost and private IP addresses are permitted."
                )
            }

        try:
            import httpx
        except ImportError:
            return {"error": "httpx not installed. Run: pip install httpx"}

        t = timeout if timeout is not None else self.default_timeout
        try:
            async with httpx.AsyncClient(timeout=t) as client:
                response = await client.request(
                    method=method.upper(),
                    url=url,
                    headers=headers or {},
                    json=body,
                    params=params or {},
                )
                latency = response.elapsed.total_seconds() * 1000 if response.elapsed else None
                logger.info(f"http_request | {method.upper()} {url} → {response.status_code}")
                return {
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "body": response.text,
                    "latency_ms": round(latency, 2) if latency else None,
                }
        except httpx.TimeoutException:
            return {"error": f"Request timed out after {t}s"}
        except Exception as e:
            logger.error(f"http_request | error: {e}")
            return {"error": str(e)}
