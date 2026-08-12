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
    #: 本地嵌入服务。空 = 不装语义那一路，召回退回纯结构化。
    #:
    #: **默认是空的**，因为语义是增强不是前提：一台没跑 Ollama 的机器
    #: 应该照样能把这个产品跑起来，而不是每次匹配都先等一个连不上的超时。
    #: 配上了它才装，装上了连不上就降级——两件事都要能观测到。
    embedding_endpoint: str = ""
    embedding_model: str = "bge-m3"
    #: 要和 `semantic_index.embedding` 的列定义对上。换模型要一起改，
    #: 对不上时嵌入适配器自己会拒绝，不会写进一批维度不对的向量。
    embedding_dimensions: int = 1024


settings = Settings()
