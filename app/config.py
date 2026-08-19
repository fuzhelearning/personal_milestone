from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_DIR = _ROOT / "config"


def resolve_app_env() -> str:
    raw = os.getenv("APP_ENV", "dev").strip().lower()
    if raw in ("prod", "production"):
        return "live"
    if raw not in ("dev", "live"):
        raise ValueError(f"APP_ENV must be 'dev' or 'live', got: {raw!r}")
    return raw


def _yaml_config_path(app_env: str) -> Path:
    path = _CONFIG_DIR / f"{app_env}.yaml"
    if not path.is_file():
        hint = (
            f"cp config/{app_env}.yaml.example config/{app_env}.yaml"
            if (_CONFIG_DIR / f"{app_env}.yaml.example").is_file()
            else f"create {_CONFIG_DIR / f'{app_env}.yaml'}"
        )
        raise FileNotFoundError(f"缺少配置文件: {path}（{hint}）")
    return path


DEFAULT_LLM_BASE_URL = "https://api.deepseek.com"
DEFAULT_LLM_MODEL = "deepseek-chat"


class Settings(BaseSettings):
    """取值来自 config/{APP_ENV}.yaml（可被环境变量覆盖）；此处不设业务默认值。"""

    app_env: str = Field(default_factory=resolve_app_env)
    database_url: str
    jwt_secret: str
    jwt_expire_seconds: int
    llm_mode: str  # mock | deepseek
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    internal_token: str
    wechat_mock: bool
    # YAML 可省略；省略时按 app_env 推断
    enable_docs: bool | None = None
    cors_origins: list[str] = Field(default_factory=list)
    cors_allow_origin_regex: str | None = None

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # 优先级（前高后低）：显式入参 > 环境变量 > config/{APP_ENV}.yaml
        yaml_file = _yaml_config_path(resolve_app_env())
        return (
            init_settings,
            env_settings,
            YamlConfigSettingsSource(settings_cls, yaml_file=yaml_file),
        )

    @field_validator("app_env")
    @classmethod
    def _normalize_env(cls, v: str) -> str:
        v = (v or "dev").strip().lower()
        if v in ("prod", "production"):
            return "live"
        if v not in ("dev", "live"):
            raise ValueError("app_env must be 'dev' or 'live'")
        return v

    @model_validator(mode="after")
    def _apply_env_defaults(self) -> Settings:
        if self.enable_docs is None:
            self.enable_docs = self.app_env == "dev"
        return self

    @property
    def is_dev(self) -> bool:
        return self.app_env == "dev"

    @property
    def is_live(self) -> bool:
        return self.app_env == "live"

    def resolved_llm_base_url(self) -> str:
        return (self.llm_base_url or "").strip() or DEFAULT_LLM_BASE_URL

    def resolved_llm_model(self) -> str:
        return (self.llm_model or "").strip() or DEFAULT_LLM_MODEL

    def validate_for_runtime(self) -> None:
        """启动硬校验：deepseek 缺 key 在任何环境都失败；live 另校弱密钥等。"""
        mode = (self.llm_mode or "").strip().lower()
        if mode not in ("mock", "deepseek"):
            raise RuntimeError(f"llm_mode 必须为 mock 或 deepseek，当前: {self.llm_mode!r}")
        if mode == "deepseek" and not (self.llm_api_key or "").strip():
            raise RuntimeError("llm_mode=deepseek 时必须配置 llm_api_key，不能回落 mock")
        if not self.is_live:
            return
        weak_jwt = {"", "dev-change-me", "change-me", "secret"}
        weak_internal = {"", "dev-internal-token", "change-me"}
        if self.jwt_secret in weak_jwt or len(self.jwt_secret) < 16:
            raise RuntimeError("live 环境 JWT_SECRET 过弱，请设置足够长的随机密钥")
        if self.internal_token in weak_internal or len(self.internal_token) < 16:
            raise RuntimeError("live 环境 INTERNAL_TOKEN 过弱，请设置足够长的随机密钥")
        if self.wechat_mock:
            raise RuntimeError("live 环境禁止 WECHAT_MOCK=true")
        if self.database_url.startswith("sqlite:"):
            raise RuntimeError("live 环境请使用非 SQLite 的 DATABASE_URL")


@lru_cache
def get_settings() -> Settings:
    return Settings()
