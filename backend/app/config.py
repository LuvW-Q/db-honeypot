"""应用配置：集中管理数据库、诱饵服务、API 与规则默认值。

所有敏感值来自环境变量或仓库根目录 `.env`，不得硬编码口令。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 仓库根目录（backend/app/config.py -> parents[2]）
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """全局配置模型（字段名与环境变量名一致，大小写不敏感）。"""

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", Path(".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- 数据库连接（按环境区分：dev / test / demo） ----
    database_url: str = Field(
        default="mysql+asyncmy://honeypot_app_rw:TestOnly-AppRw-2026@127.0.0.1:3306/honeypot_dev?charset=utf8mb4"
    )
    readonly_database_url: str = Field(
        default="mysql+asyncmy://honeypot_app_ro:TestOnly-AppRo-2026@127.0.0.1:3306/honeypot_dev?charset=utf8mb4"
    )
    migrate_database_url: str = Field(
        default="mysql+asyncmy://honeypot_migrate:TestOnly-Migrate-2026@127.0.0.1:3306/honeypot_dev?charset=utf8mb4"
    )
    test_database_url: str = Field(
        default="mysql+asyncmy://honeypot_migrate:TestOnly-Migrate-2026@127.0.0.1:3306/honeypot_test?charset=utf8mb4"
    )

    # ---- 诱饵服务 ----
    honeypot_host: str = "127.0.0.1"
    honeypot_port: int = 3307
    honeypot_service_name: str = "mysql-honeypot"
    honeypot_accounts: str = "demo_reader:TestOnly-Decoy-01,demo_admin:TestOnly-Decoy-02"
    honeypot_allowed_client_cidrs: str = "127.0.0.1/32,172.28.0.0/24"

    # ---- Web API ----
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    web_dist_dir: str = "../frontend/dist"
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    # ---- 业务参数 ----
    data_retention_days: int = 30
    ai_enabled: bool = False
    log_level: str = "INFO"

    @field_validator("honeypot_port", "api_port", "data_retention_days", mode="after")
    @classmethod
    def _positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("端口与保留天数必须为正整数")
        return value

    @property
    def decoy_accounts(self) -> dict[str, str]:
        """解析预置诱饵账号，返回 {用户名: 口令}。

        格式：`user1:pass1,user2:pass2`；仅用于隔离实验环境的虚构账号。
        """
        accounts: dict[str, str] = {}
        for item in self.honeypot_accounts.split(","):
            item = item.strip()
            if not item:
                continue
            username, _, password = item.partition(":")
            if username and password:
                accounts[username] = password
        return accounts

    @property
    def allowed_cidrs(self) -> list[str]:
        """允许连接诱饵/运行模拟器的隔离网段列表。"""
        return [c.strip() for c in self.honeypot_allowed_client_cidrs.split(",") if c.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回进程内单例配置。"""
    return Settings()


settings = get_settings()
