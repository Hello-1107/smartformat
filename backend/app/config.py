"""应用配置。

所有环境变量集中在 backend/.env，通过 pydantic-settings 读取。
DeepSeek API Key 只存在于后端环境，绝不进入前端源码或构建产物。
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator, Field

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 数据库
    database_url: str = "sqlite:///./smart_format.db"

    # 鉴权
    secret_key: str = "dev-secret-change-me-in-production"
    access_token_expire_minutes: int = 1440
    algorithm: str = "HS256"
    environment: str = "development"

    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # 文件存储
    storage_dir: str = "./uploads"
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    max_uncompressed_bytes: int = Field(default=100 * 1024 * 1024, gt=0)
    max_zip_entries: int = Field(default=3000, gt=0)
    workspace_quota_bytes: int = Field(default=500 * 1024 * 1024, gt=0)
    pdftoppm_command: str = "pdftoppm"
    tesseract_command: str = "tesseract"
    tessdata_dir: str = ""
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @model_validator(mode="after")
    def production_key(self) -> "Settings":
        if self.environment == "production" and (self.secret_key == "dev-secret-change-me-in-production" or len(self.secret_key) < 32):
            raise ValueError("生产环境必须配置至少 32 字符的独立 SECRET_KEY")
        return self

    @property
    def storage_path(self) -> Path:
        path = Path(self.storage_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
