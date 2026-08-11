"""随产品发布的行动类别。

这是**配置，不是领域**——所以它在领域核心外面。加一个校园新场景只需要
在这个元组里加一条，首屏自动多一张卡，撮合窗口和风险控制自动跟上。
"""

from __future__ import annotations

from datetime import timedelta

from cofield.domain.model.action_kind import (
    ActionKind,
    ActionKindRegistry,
    AgentReplyPolicy,
    PlacePrecision,
    RiskTier,
    SeatModel,
    StarterCard,
)

DEFAULT_KINDS: tuple[ActionKind, ...] = (
    ActionKind(
        key="contest_team",
        label="比赛组队",
        starter=StarterCard(
            title="比赛组队",
            example="想组队打下个月的创新创业大赛，我做产品，缺一个后端和一个做 PPT 的",
        ),
        seat_model=SeatModel(roles=("队长", "开发", "设计", "汇报"), minimum=2, maximum=6),
        matching_window=timedelta(hours=12),
        echo_template=("submission", "credit_list"),
    ),
    ActionKind(
        key="course_project",
        label="课程项目",
        starter=StarterCard(
            title="课程项目",
            example="数据库课设要三个人一组，我能写后端，还差两个人，下周五交",
        ),
        seat_model=SeatModel(roles=("开发", "文档", "汇报"), minimum=2, maximum=5),
        matching_window=timedelta(hours=6),
        echo_template=("submission", "grade_evidence"),
    ),
    ActionKind(
        key="creative_work",
        label="作品创作",
        starter=StarterCard(
            title="作品创作",
            example="我想做一个关于校园流浪猫的一分钟短片，周五前完成。我会写脚本，但不认识会拍摄和剪辑的人",
        ),
        seat_model=SeatModel(
            roles=("策划", "拍摄", "剪辑", "配乐"), minimum=2, maximum=6
        ),
        matching_window=timedelta(hours=6),
        echo_template=("video_artifact", "credit_list"),
    ),
    ActionKind(
        key="study_buddy",
        label="学习搭子",
        starter=StarterCard(
            title="学习搭子",
            example="想找人一起备考六级，每周三晚上在图书馆，能互相监督就行",
        ),
        seat_model=SeatModel(roles=("同学",), minimum=2, maximum=4),
        matching_window=timedelta(hours=24),
        echo_template=("attendance",),
    ),
    ActionKind(
        key="internship_help",
        label="实习互助",
        starter=StarterCard(
            title="实习互助",
            example="在准备暑期实习，想找人互相模拟面试，我可以帮忙看简历",
        ),
        seat_model=SeatModel(roles=("同学",), minimum=2, maximum=3),
        matching_window=timedelta(hours=24),
        # 会聊到简历、薪资这类敏感信息，代答一律披露。
        agent_reply_policy=AgentReplyPolicy.ALWAYS_DISCLOSE,
        echo_template=("feedback",),
    ),
    ActionKind(
        key="outdoor_trip",
        label="户外同行",
        starter=StarterCard(
            title="户外同行",
            example="周末想去爬山看日出，找两三个同行的，早上五点出发",
        ),
        seat_model=SeatModel(roles=("同行",), minimum=2, maximum=6),
        # 线下、可能偏远、可能夜间——地点只到校区，且不开放自动成局。
        risk_tier=RiskTier.HIGH,
        place_precision=PlacePrecision.CAMPUS,
        agent_reply_policy=AgentReplyPolicy.ALWAYS_DISCLOSE,
        matching_window=timedelta(hours=24),
        echo_template=("photo",),
    ),
)

registry = ActionKindRegistry(DEFAULT_KINDS)
