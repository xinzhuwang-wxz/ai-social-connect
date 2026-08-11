"""运行期配置。"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COFIELD_", extra="ignore")

    database_url: str = "postgresql+psycopg://cofield:cofield@localhost:5432/cofield"
    #: 真实校园租户。仿真跑在另一个 campus_id 上，见 06-仿真与测试人口。
    default_campus: str = "demo-campus"
    simulation_campus: str = "simulation"
    #: 演示模式：时钟可被推着走。
    #:
    #: 这个产品的核心循环里有两处"要等"——撮合窗口六小时、记忆回流两周。
    #: 演示时不能真等，而 `SimulatedClock` 本来就是为此存在的，缺的只是
    #: 一个能推它的入口。
    #:
    #: **它是开关而不是端点自带的鉴权**，因为一个"能改系统时间"的接口
    #: 在生产里不该只是权限不够，而应该**根本不存在**——关掉时那条路由
    #: 不注册，探测不到。
    demo_mode: bool = False


settings = Settings()
