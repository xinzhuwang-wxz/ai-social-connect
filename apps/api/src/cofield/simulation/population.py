"""合成校园人口。

**唯一被替换的是"人"。** 数据库、求解器、检索都是真的，只有这里的主体
是合成的。

四个维度必须有结构，随机会把系统测得过于乐观：

1. **技能长尾** —— 会写文案的几百人，会调色的十几个。均匀分布会让角色覆盖
   约束假性容易满足，稀缺角色永远不会成为瓶颈。
2. **时间受课表约束** —— 同专业同年级的人上同一批课，冲突是**相关**的。
   均匀随机的时间几乎总能找到交集，时间约束会形同虚设。这是最危险的一个。
3. **社交网络有社区结构** —— 用学生 × 课程/社团的二部隶属网络生成，再投影。
   这和领域模型同构（人-人关系是二部图的投影），不是两套假设。
4. **意图到达集中在截止期前** —— 不是均匀泊松。撮合窗口的效果全看这个。

给定种子完全可复现——仿真结论必须能被重跑验证。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import networkx as nx

#: 一周 7 天 × 3 段（上午/下午/晚上）。位 0 是周一上午。
SLOTS_PER_DAY = 3
WEEK_SLOTS = 7 * SLOTS_PER_DAY

MAJORS: tuple[tuple[str, float], ...] = (
    ("计算机", 0.14), ("新闻传播", 0.08), ("电子信息", 0.10), ("工商管理", 0.11),
    ("机械工程", 0.09), ("外国语", 0.07), ("数学", 0.05), ("设计", 0.06),
    ("生物", 0.06), ("法学", 0.05), ("材料", 0.06), ("土木", 0.06),
    ("经济", 0.07),
)

#: 技能的相对丰度。数字越大人越多——这就是长尾。
#: 会写文案的比会调色的多两个数量级，这决定了哪个角色是真瓶颈。
SKILL_ABUNDANCE: dict[str, float] = {
    "写文案": 1.00, "做PPT": 0.92, "拍照": 0.61, "翻译": 0.44,
    "写脚本": 0.30, "数据分析": 0.28, "前端": 0.22, "海报设计": 0.20,
    "后端": 0.18, "拍摄": 0.16, "主持": 0.12, "剪辑": 0.09,
    "配乐": 0.05, "调色": 0.03, "三维建模": 0.025, "动效": 0.02,
}

CLUB_NAMES: tuple[str, ...] = (
    "影像协会", "辩论队", "篮球社", "动漫社", "创业协会", "机器人队",
    "合唱团", "摄影社", "志愿者协会", "英语角", "街舞社", "科创中心",
)

CAMPUS_ZONES: tuple[str, ...] = ("东校区", "西校区", "南校区")

_SURNAMES = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
_GIVEN = "然轩宇泽睿曦航嘉磊佳怡欣悦茜蕾晨旭霖沐禾一凡子墨昀笙桐屿"


@dataclass(frozen=True, slots=True)
class SyntheticPerson:
    id: UUID
    display_name: str
    major: str
    year: int
    zone: str
    skills: tuple[str, ...]
    #: 长度 21 的 "0"/"1" 串，1 表示这一时段有空。
    availability: str
    #: 参加的课程与社团。人-人关系由它投影，不单独存。
    affiliations: tuple[str, ...]
    #: 历史分层：0 = 零历史，1 = 一到三个切面，2 = 重复协作。
    history_tier: int


@dataclass(frozen=True, slots=True)
class Population:
    people: tuple[SyntheticPerson, ...]
    #: 学生 × 群体的二部隶属网络。人-人网络是它的投影（Breiger 二重性）。
    affiliation_graph: nx.Graph = field(compare=False, repr=False)

    def __len__(self) -> int:
        return len(self.people)

    def by_skill(self, skill: str) -> tuple[SyntheticPerson, ...]:
        return tuple(p for p in self.people if skill in p.skills)

    def scarcity(self) -> dict[str, int]:
        """每个技能有多少人。长尾生效时这份表会很不平。"""
        counts: dict[str, int] = {s: 0 for s in SKILL_ABUNDANCE}
        for person in self.people:
            for skill in person.skills:
                counts[skill] += 1
        return dict(sorted(counts.items(), key=lambda kv: kv[1]))


def _weighted_choice(rng: random.Random, options: tuple[tuple[str, float], ...]) -> str:
    total = sum(w for _, w in options)
    roll = rng.uniform(0, total)
    upto = 0.0
    for name, weight in options:
        upto += weight
        if roll <= upto:
            return name
    return options[-1][0]


def _course_load(rng: random.Random, major: str, year: int) -> list[str]:
    """一个学生这学期上的课。

    同专业同年级共享必修课——这正是让时间冲突**相关**而不是独立的机制。
    """
    required = [f"{major}-必修{year}-{i}" for i in range(1, 5)]
    electives = [f"通识-{rng.randrange(1, 30)}" for _ in range(rng.randint(1, 3))]
    return required + electives


def _availability_from_courses(rng: random.Random, courses: list[str]) -> str:
    """课表决定空闲。同一门课的人被占掉同一批时段。"""
    busy = set()
    for course in courses:
        # 课程名决定它占哪个时段——同一门课对所有人占同一格。
        slot = hash(course) % WEEK_SLOTS
        busy.add(slot)
        if rng.random() < 0.5:  # 双课时
            busy.add((slot + 1) % WEEK_SLOTS)
    # 深夜与周末早晨大多数人也不排活动
    for slot in (2, 5, 8, 11, 14):
        if rng.random() < 0.35:
            busy.add(slot)
    return "".join("0" if i in busy else "1" for i in range(WEEK_SLOTS))


def _skills_for(rng: random.Random, major: str) -> tuple[str, ...]:
    """按丰度抽技能，专业相关的加权。

    抽出来的分布是长尾的——这决定了「缺一个会调色的」是不是真的难。
    """
    affinity = {
        "计算机": ("前端", "后端", "数据分析"),
        "新闻传播": ("写脚本", "拍摄", "剪辑", "主持"),
        "设计": ("海报设计", "调色", "动效", "三维建模"),
        "电子信息": ("后端", "数据分析"),
        "外国语": ("翻译", "写文案"),
    }.get(major, ())

    chosen: list[str] = []
    for skill, abundance in SKILL_ABUNDANCE.items():
        p = abundance * 0.28
        if skill in affinity:
            p *= 4.0
        if rng.random() < min(p, 0.9):
            chosen.append(skill)
    if not chosen:
        chosen.append(_weighted_choice(rng, (("写文案", 1.0), ("做PPT", 0.9))))
    return tuple(chosen[:5])


def _history_tier(rng: random.Random) -> int:
    """45% 零历史 / 35% 一到三个切面 / 20% 重复协作。

    零历史那一层是用来验证冷启动公平的——demo 主角必须来自这一层。
    """
    roll = rng.random()
    return 0 if roll < 0.45 else (1 if roll < 0.80 else 2)


def generate(*, size: int = 20_000, seed: int = 20260812) -> Population:
    """造一个校园。给定 seed 完全可复现。"""
    rng = random.Random(seed)
    graph = nx.Graph()
    people: list[SyntheticPerson] = []

    for index in range(size):
        major = _weighted_choice(rng, MAJORS)
        year = rng.choices((1, 2, 3, 4), weights=(0.28, 0.27, 0.24, 0.21))[0]
        courses = _course_load(rng, major, year)
        clubs = rng.sample(CLUB_NAMES, k=rng.choices((0, 1, 2), weights=(0.35, 0.45, 0.20))[0])

        person = SyntheticPerson(
            id=uuid4(),
            display_name=(
                f"{rng.choice(_SURNAMES)}{rng.choice(_GIVEN)}{rng.choice(_GIVEN)}"
            ),
            major=major,
            year=year,
            zone=rng.choices(CAMPUS_ZONES, weights=(0.5, 0.3, 0.2))[0],
            skills=_skills_for(rng, major),
            availability=_availability_from_courses(rng, courses),
            affiliations=tuple(courses + clubs),
            history_tier=_history_tier(rng),
        )
        people.append(person)

        # 二部图：一边是人，一边是群体。人-人关系是它的投影，不单独存。
        graph.add_node(person.id, bipartite=0)
        for group in person.affiliations:
            graph.add_node(group, bipartite=1)
            graph.add_edge(person.id, group)

        if index and index % 5000 == 0:
            rng.shuffle(people)  # 避免生成顺序泄漏成任何排序信号

    return Population(people=tuple(people), affiliation_graph=graph)


# --- 意图到达 ---------------------------------------------------------------

_GOALS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("拍一支{n}秒的校园短片", ("拍摄", "剪辑"), "creative_work"),
    ("做一个数据库课设", ("后端", "写文案"), "course_project"),
    ("组队打创新创业大赛", ("做PPT", "数据分析"), "contest_team"),
    ("准备一场社团招新宣传", ("海报设计", "写文案"), "creative_work"),
    ("拍一组毕业照", ("拍照", "调色"), "creative_work"),
    ("做一个小程序原型", ("前端", "后端"), "course_project"),
    ("找人一起备考六级", (), "study_buddy"),
    ("互相模拟面试", (), "internship_help"),
    ("周末去爬山看日出", (), "outdoor_trip"),
)


@dataclass(frozen=True, slots=True)
class SyntheticIntent:
    person: SyntheticPerson
    expression: str
    kind_key: str
    needs: tuple[str, ...]
    offers: tuple[str, ...]
    created_at: datetime
    deadline: datetime


def arrivals(
    population: Population,
    *,
    now: datetime,
    count: int = 400,
    seed: int = 20260812,
) -> tuple[SyntheticIntent, ...]:
    """活跃意图池。

    到达集中在截止期之前而不是均匀分布——撮合窗口的效果全看这个。
    表达质量刻意参差：说得清楚的、含糊的、夹带无关信息的都有，
    否则意图理解的失败路径根本测不到。
    """
    rng = random.Random(seed ^ 0x9E37)
    chosen = rng.sample(population.people, k=min(count, len(population.people)))
    out: list[SyntheticIntent] = []

    for person in chosen:
        template, needs, kind = rng.choice(_GOALS)
        goal = template.format(n=rng.choice((30, 60, 90)))

        # 截止期分布：多数在一周内，少数更远。
        days_out = rng.choices((1, 2, 3, 5, 7, 14, 30), weights=(8, 12, 16, 14, 10, 6, 2))[0]
        deadline = (now + timedelta(days=days_out)).replace(
            hour=23, minute=59, second=0, microsecond=0
        )
        # 到达时间贴着截止期——离 deadline 越近，越可能是刚发的。
        lead = timedelta(hours=rng.triangular(0, days_out * 24, days_out * 6))
        created = max(now - lead, now - timedelta(days=days_out))

        want = tuple(n for n in needs if n not in person.skills)
        give = tuple(s for s in person.skills if s in SKILL_ABUNDANCE)[:2]
        out.append(
            SyntheticIntent(
                person=person,
                expression=_phrase(rng, goal, want, give, days_out),
                kind_key=kind,
                needs=want,
                offers=give,
                created_at=created,
                deadline=deadline,
            )
        )
    return tuple(out)


def _phrase(
    rng: random.Random,
    goal: str,
    needs: tuple[str, ...],
    offers: tuple[str, ...],
    days: int,
) -> str:
    """把结构化内容说成一句人话，质量刻意参差。"""
    when = {1: "明天", 2: "后天", 3: "三天内", 5: "五天内", 7: "一周内"}.get(
        days, f"{days}天内"
    )
    style = rng.random()

    if style < 0.15:
        # 含糊：只说想干什么
        return f"想{goal}"
    if style < 0.30:
        # 夹带无关信息
        return (
            f"最近有点忙但还是想{goal}，{when}要，"
            f"{'我会' + '和'.join(offers) if offers else '没什么特长'}，"
            f"{'缺' + '和'.join(needs) if needs else '随便来个人就行'}"
        )
    if style < 0.40 and needs:
        # 否定式表达需求——最常见的说法
        mine = "和".join(offers) or "打杂"
        theirs = "和".join(needs)
        return f"想{goal}，{when}完成。我会{mine}，但不认识会{theirs}的人"
    # 说得清楚
    parts = [f"想{goal}", f"{when}完成"]
    if offers:
        parts.append(f"我能做{'、'.join(offers)}")
    if needs:
        parts.append(f"缺{'、'.join(needs)}")
    return "，".join(parts)
