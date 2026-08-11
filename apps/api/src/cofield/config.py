"""运行期配置。"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COFIELD_", extra="ignore")

    database_url: str = "postgresql+psycopg://cofield:cofield@localhost:5432/cofield"
    #: 真实校园租户。仿真跑在另一个 campus_id 上，见 06-仿真与测试人口。
    default_campus: str = "demo-campus"
    simulation_campus: str = "simulation"


settings = Settings()
