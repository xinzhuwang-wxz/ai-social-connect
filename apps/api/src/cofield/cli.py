"""命令行：把一个空库变成一个能打开就用的校园。

## 为什么这件事重要到值得一个命令

"起来就有数据"是交付物的一部分，不是开发便利。一个空库让人对着空白页
发呆——他不知道这产品能干嘛，也没有任何东西可以点。而这个产品的价值
恰恰要在**有人的校园里**才看得见：稀缺角色成为瓶颈、时间凑不上、
放宽一项能多出多少人，全都是人口结构的函数。

## 合成人口住在自己的租户里

`campus_id="simulation"`，且每一行都带 `is_synthetic`。真人租户
（`demo-campus`）里一个合成主体都看不到——这不是靠查询时记得加条件，
是靠行级安全。演示时两边都在，互不干扰。
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta
from uuid import uuid4

import sqlalchemy as sa

from cofield.adapters.clock import SystemClock
from cofield.adapters.persistence.engine import build_engine, owner_connection
from cofield.adapters.persistence.opportunities import (
    OpportunityRepository,
    OrganizationRepository,
)
from cofield.adapters.persistence.principals import PrincipalRepository
from cofield.config import settings
from cofield.domain.model.opportunity import ActionOpportunity, Organization, Seat
from cofield.domain.model.principal import CampusId, Principal
from cofield.simulation.loader import load_principals
from cofield.simulation.population import generate

SIM_CAMPUS = "simulation"
DEMO_CAMPUS = "demo-campus"

#: 组织的名字与它常发的活动类别。真实校园里发招募的就是这些人。
ORGANIZERS: tuple[tuple[str, str], ...] = (
    ("影像协会", "creative_work"),
    ("学生科创中心", "contest_team"),
    ("新闻传播学院团委", "creative_work"),
    ("机器人队", "contest_team"),
    ("英语角", "study_buddy"),
    ("志愿者协会", "outdoor_trip"),
    ("创业孵化基地", "internship_help"),
    ("计算机学院实验室", "course_project"),
    ("摄影社", "creative_work"),
    ("辩论队", "contest_team"),
)

#: 招募的题目与它缺的角色。
BRIEFS: tuple[tuple[str, str, tuple[tuple[str, int], ...]], ...] = (
    ("校园开放日宣传片", "拍一支三分钟的开放日宣传片", (("拍摄", 2), ("剪辑", 1))),
    ("院系招新海报", "做一套院系招新的视觉物料", (("海报设计", 2), ("写文案", 1))),
    ("互联网+ 参赛队", "组一支参加互联网+ 的队伍", (("做PPT", 1), ("数据分析", 2))),
    ("机器人大赛备赛", "备战今年的机器人大赛", (("后端", 2), ("三维建模", 1))),
    ("六级冲刺小组", "一起冲一次六级", (("翻译", 1),)),
    ("周末登山", "周末去后山看日出", (("拍照", 1),)),
    ("模拟面试互助", "互相模拟一次技术面试", (("数据分析", 1),)),
    ("数据库课设组队", "做一个数据库课程设计", (("后端", 2), ("前端", 1))),
    ("毕业照跟拍", "给毕业班拍一组照片", (("拍照", 2), ("调色", 1))),
    ("辩论赛资料组", "帮辩论队整理立论资料", (("写文案", 2),)),
    ("短视频栏目", "做一档校园短视频栏目", (("写脚本", 1), ("剪辑", 2), ("配乐", 1))),
    ("科普动画", "做一支两分钟的科普动画", (("动效", 1), ("配乐", 1))),
)


def _seed(size: int, seed: int, url: str) -> int:
    engine = build_engine(url)
    clock = SystemClock()
    now = clock.now()

    with owner_connection(engine) as conn:
        conn.execute(
            sa.text(
                "TRUNCATE principals, intent_signals, organizations, "
                "action_opportunities, opportunity_seats, match_envelopes, "
                "consent_records, semantic_index, formation_proposals, "
                "commitments, shared_events, event_members, spaces, space_items, "
                "negotiation_tasks, negotiation_messages, evidence, memory_facets "
                "CASCADE"
            )
        )

    population = generate(size=size, seed=seed)
    load_principals(engine, population, campus_id=SIM_CAMPUS, now=now)
    print(f"合成人口 {len(population)} 人 → {SIM_CAMPUS}")

    _organizers(engine, clock, population, now=now, seed=seed)
    demo = _demo_person(engine, clock)
    print(f"演示账号 {demo.display_name} → {DEMO_CAMPUS}（id {demo.id}）")
    _organizers_for_real_people(engine, clock, demo, now=now, seed=seed)
    print()
    print("打开 http://localhost:3000 ，请求头带：")
    print(f"  X-Principal-Id: {demo.id}")
    print(f"  X-Campus-Id: {DEMO_CAMPUS}")
    return 0


def _organizers(
    engine: object, clock: SystemClock, population: object, *, now: datetime, seed: int
) -> None:
    """建组织与招募。

    组织一律 `verified=True`：未验证的组织不能发布招募，而一个
    "起来就有数据"的环境里如果招募全发不出去，这条规则就演示不出来。
    """
    rng = random.Random(seed)
    people = population.people  # type: ignore[attr-defined]

    with owner_connection(engine) as conn:  # type: ignore[arg-type]
        orgs = OrganizationRepository(conn, clock, SIM_CAMPUS)
        opps = OpportunityRepository(conn, clock, SIM_CAMPUS)

        created = []
        for name, _kind in ORGANIZERS:
            organization = Organization(
                id=uuid4(),
                campus_id=CampusId(SIM_CAMPUS),
                name=name,
                verified=True,
            )
            orgs.add(organization)
            created.append(organization)

        count = 0
        for index, (title, goal, roles) in enumerate(BRIEFS):
            # 每个题目发 3–5 份，落到不同组织、不同截止期上——
            # 全挤在同一天会让"截止期临近的单独提前清算"演示不出来。
            for copy in range(rng.randint(3, 5)):
                organization = created[(index + copy) % len(created)]
                steward = rng.choice(people)
                opps.add(
                    ActionOpportunity(
                        id=uuid4(),
                        organization_id=organization.id,
                        kind_key=ORGANIZERS[(index + copy) % len(ORGANIZERS)][1],
                        title=f"{title}（{organization.name}）",
                        goal=goal,
                        seats=tuple(
                            Seat(role=role, capacity=capacity) for role, capacity in roles
                        ),
                        steward_id=steward.id,
                        deadline=now + timedelta(days=rng.randint(3, 21)),
                        created_at=now,
                        location_scope=rng.choice(
                            ("东校区", "西校区", "南校区", None)
                        ),
                    )
                )
                count += 1

    print(f"组织 {len(created)} 个、招募 {count} 份 → {SIM_CAMPUS}")


def _organizers_for_real_people(
    engine: object, clock: SystemClock, steward: Principal, *, now: datetime, seed: int
) -> None:
    """真人租户里也要有组织和招募。

    ## 为什么这不是可选的

    真人打开的是 `demo-campus`，而上面那一批全播在 `simulation`。于是
    一个刚打开这个网页的人看到的是：

    - 「有哪些招募」空的
    - 「发一份招募」一句"还没有哪个组织能在这里招人"——**死路**
    - 而这两屏在仿真租户里都是满的

    每一片都做好了，真人那一侧却是空的。这个洞躲过了所有测试，因为
    测试自己建数据；也躲过了仿真，因为仿真跑在另一个租户上。

    ## 为什么这不违反租户隔离

    隔离要挡的是**合成主体出现在真人面前**——真人不该以为自己在和真人
    配队。组织和招募不是人：一份经核验的社团招募是现实里真实存在的东西。
    所以这里的 `steward_id` 指向**真人租户里那个真人账号**，
    一个合成主体都不跨过来。

    份数比仿真那边少：这一屏是给人看的，不是给基准跑的。
    """
    rng = random.Random(seed + 1)

    with owner_connection(engine) as conn:  # type: ignore[arg-type]
        orgs = OrganizationRepository(conn, clock, DEMO_CAMPUS)
        opps = OpportunityRepository(conn, clock, DEMO_CAMPUS)

        created = []
        for name, _kind in ORGANIZERS:
            organization = Organization(
                id=uuid4(),
                campus_id=CampusId(DEMO_CAMPUS),
                name=name,
                verified=True,
            )
            orgs.add(organization)
            created.append(organization)

        count = 0
        for index, (title, goal, roles) in enumerate(BRIEFS):
            organization = created[index % len(created)]
            opps.add(
                ActionOpportunity(
                    id=uuid4(),
                    organization_id=organization.id,
                    kind_key=ORGANIZERS[index % len(ORGANIZERS)][1],
                    title=f"{title}（{organization.name}）",
                    goal=goal,
                    seats=tuple(
                        Seat(role=role, capacity=capacity) for role, capacity in roles
                    ),
                    steward_id=steward.id,
                    deadline=now + timedelta(days=rng.randint(3, 21)),
                    created_at=now,
                    location_scope=rng.choice(("东校区", "西校区", "南校区", None)),
                )
            )
            count += 1

    print(f"组织 {len(created)} 个、招募 {count} 份 → {DEMO_CAMPUS}")


def _demo_person(engine: object, clock: SystemClock) -> Principal:
    """一个真人租户里的演示账号。

    它**不是**合成主体——真人永远不该以为自己在和真人配队，所以演示时
    这个账号看到的候选来自 `simulation` 租户还是 `demo-campus`，
    取决于请求头里的 `X-Campus-Id`，两边的数据不会串。
    """
    person = Principal(
        id=uuid4(),
        campus_id=CampusId(DEMO_CAMPUS),
        display_name="林知遥",
        is_synthetic=False,
        self_intro="写东西不爱端着，句子里得带点攻击性才舒服。喜欢先做个粗糙版本出来再一起改。",
        major="新闻传播",
    )
    with owner_connection(engine) as conn:  # type: ignore[arg-type]
        PrincipalRepository(conn, clock).add(person)
    return person


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cofield", description="共域 CoField")
    sub = parser.add_subparsers(dest="command", required=True)

    seed_cmd = sub.add_parser("seed", help="把一个空库变成一个能用的校园")
    seed_cmd.add_argument("--size", type=int, default=20_000, help="合成人口规模")
    seed_cmd.add_argument("--seed", type=int, default=20260812, help="随机种子")
    seed_cmd.add_argument("--url", default=settings.database_url)

    args = parser.parse_args(argv)
    if args.command == "seed":
        return _seed(args.size, args.seed, args.url)
    return 1


if __name__ == "__main__":
    sys.exit(main())
