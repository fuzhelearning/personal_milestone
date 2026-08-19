"""DeepSeek OpenAI 兼容 Chat Completions。"""

from __future__ import annotations

import httpx

from app.config import get_settings

CALL_TIMEOUT_SECONDS = 60.0


class DeepSeekCallError(RuntimeError):
    """HTTP / 超时 / 响应解析失败。"""

    def __init__(self, message: str, *, raw_response: str = ""):
        super().__init__(message)
        self.raw_response = raw_response


def chat_completions(messages: list[dict], *, max_tokens: int | None = None) -> str:
    """POST {base}/chat/completions，要求 json_object，返回 assistant 正文。"""
    settings = get_settings()
    base = settings.resolved_llm_base_url().rstrip("/")
    model = settings.resolved_llm_model()
    api_key = (settings.llm_api_key or "").strip()
    if not api_key:
        raise DeepSeekCallError("llm_api_key 为空")

    url = f"{base}/chat/completions"
    body = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=CALL_TIMEOUT_SECONDS) as client:
            resp = client.post(url, json=body, headers=headers)
    except httpx.TimeoutException as exc:
        raise DeepSeekCallError("DeepSeek 调用超时（60s）") from exc
    except httpx.HTTPError as exc:
        raise DeepSeekCallError(f"DeepSeek 网络错误: {exc}") from exc

    text = resp.text or ""
    if resp.status_code >= 400:
        raise DeepSeekCallError(
            f"DeepSeek HTTP {resp.status_code}",
            raw_response=text,
        )
    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise DeepSeekCallError("DeepSeek 响应格式无效", raw_response=text) from exc
    if content is None:
        raise DeepSeekCallError("DeepSeek 返回空 content", raw_response=text)
    return str(content)
