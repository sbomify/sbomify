from __future__ import annotations

from typing import Any, Mapping

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

DEFAULT_TIMEOUT = (3.05, 10)


@retry(
    retry=retry_if_exception_type(requests.RequestException),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    stop=stop_after_attempt(3),
    reraise=True,
)
def request_with_retry(
    method: str,
    url: str,
    *,
    timeout: tuple[float, float] | float = DEFAULT_TIMEOUT,
    **kwargs: Any,
) -> requests.Response:
    return requests.request(method, url, timeout=timeout, **kwargs)


def post_form(
    url: str,
    data: Mapping[str, Any],
    *,
    timeout: tuple[float, float] | float = DEFAULT_TIMEOUT,
    **kwargs: Any,
) -> requests.Response:
    return request_with_retry("POST", url, data=data, timeout=timeout, **kwargs)


def get_json(
    url: str,
    *,
    timeout: tuple[float, float] | float = DEFAULT_TIMEOUT,
    **kwargs: Any,
) -> requests.Response:
    headers = kwargs.pop("headers", {})
    headers.setdefault("Accept", "application/json")
    return request_with_retry("GET", url, headers=headers, timeout=timeout, **kwargs)
