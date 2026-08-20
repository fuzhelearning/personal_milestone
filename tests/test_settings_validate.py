"""启动校验：deepseek 空 key 失败；mock 无 key 可启动。"""

from __future__ import annotations

import pytest

from app.config import Settings


def _base_kwargs(**overrides):
    data = {
        "app_env": "dev",
        "database_url": "sqlite:///:memory:",
        "jwt_secret": "dev-change-me",
        "jwt_expire_seconds": 7200,
        "llm_mode": "mock",
        "llm_api_key": "",
        "llm_base_url": "",
        "llm_model": "",
        "internal_token": "dev-internal-token",
        "wechat_mock": True,
        "celery_broker_url": "amqp://guest:guest@127.0.0.1:5672//",
        "celery_result_backend": "",
        "celery_task_always_eager": False,
    }
    data.update(overrides)
    return data


def test_mock_without_key_can_start():
    s = Settings(**_base_kwargs(llm_mode="mock", llm_api_key=""))
    s.validate_for_runtime()  # 不抛


def test_deepseek_empty_key_fails_in_dev():
    s = Settings(**_base_kwargs(llm_mode="deepseek", llm_api_key=""))
    with pytest.raises(RuntimeError, match="llm_api_key"):
        s.validate_for_runtime()


def test_deepseek_empty_key_fails_in_live():
    s = Settings(
        **_base_kwargs(
            app_env="live",
            llm_mode="deepseek",
            llm_api_key="",
            jwt_secret="long-enough-secret-key",
            internal_token="long-enough-internal-token",
            wechat_mock=False,
            database_url="mysql+pymysql://u:p@127.0.0.1:3306/db",
        )
    )
    with pytest.raises(RuntimeError, match="llm_api_key"):
        s.validate_for_runtime()


def test_deepseek_with_key_ok_in_dev():
    s = Settings(**_base_kwargs(llm_mode="deepseek", llm_api_key="sk-test"))
    s.validate_for_runtime()


def test_empty_base_url_and_model_fallback():
    s = Settings(**_base_kwargs(llm_mode="deepseek", llm_api_key="sk-test", llm_base_url="", llm_model=""))
    assert s.resolved_llm_base_url() == "https://api.deepseek.com"
    assert s.resolved_llm_model() == "deepseek-chat"
