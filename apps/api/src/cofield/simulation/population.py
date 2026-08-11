"""合成校园人口。

**唯一被替换的是"人"。** 数据库、求解器、检索都是真的，只有这里的主体
是合成的。

六个维度必须有结构，随机会把系统测得过于乐观：

1. **技能长尾** —— 会写文案的几百人，会调色的十几个。均匀分布会让角色覆盖
   约束假性容易满足，稀缺角色永远不会成为瓶颈。
2. **时间受课表约束** —— 同专业同年级的人上同一批课，冲突是**相关**的。
   均匀随机的时间几乎总能找到交集，时间约束会形同虚设。这是最危险的一个。
3. **社交网络有社区结构** —— 用学生 × 课程/社团的二部隶属网络生成，再投影。
   这和领域模型同构（人-人关系是二部图的投影），不是两套假设。
4. **意图到达集中在截止期前** —— 不是均匀泊松。撮合窗口的效果全看这个。
5. **表达风格与技能正交** —— 会写文案的八千人里，文风各不相同。风格是
   **没有字段装得下**的东西，它是语义召回存在的全部理由；如果它能被技能
   或专业预测出来，那结构化召回就够了，语义那一路是摆设。
6. **校区跟着院系走** —— 设计学院在一栋楼里。独立随机抽会让地点约束
   形同虚设，跟时间那一条是同一个陷阱。

第 5 条和其余五条**方向相反**：那五条要的是相关性，这一条要的是独立性。
风格一旦能被专业预测，语义召回就成了结构化召回的影子。

给定种子完全可复现——仿真结论必须能被重跑验证。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from hashlib import blake2b
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
#:
#: **键必须和 `domain.model.skills.SKILLS` 完全一致**（有测试守着）：
#: 两处各写一份的话，仿真里会出现现实中抽不出来的技能，
#: 那种测试跑得再绿也证明不了什么。
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

#: 院系所在的校区。**校区不是独立随机抽的**——设计学院就在一栋楼里，
#: 学美术的人绝大多数在同一个校区上课。
#:
#: 独立随机抽会让地点约束形同虚设：全校有人会的技能，每个校区都恰好有人会，
#: 于是"缺个会调色的，在南校区"永远不会真的卡住，「放宽地点」这条路径
#: 一次都跑不到。这和时间那一条是同一个陷阱——随机让系统显得过于乐观。
MAJOR_HOME_ZONE: dict[str, str] = {
    "计算机": "东校区", "电子信息": "东校区", "数学": "东校区",
    "机械工程": "东校区", "材料": "东校区", "土木": "东校区",
    "设计": "西校区", "新闻传播": "西校区", "外国语": "西校区",
    "工商管理": "南校区", "经济": "南校区", "法学": "南校区",
    "生物": "南校区",
}

#: 待在本院系校区的比例。剩下的散到别处——通识课、跨校区社团、
#: 搬过宿舍的人都真实存在，卡得太死会走到另一个极端。
HOME_ZONE_SHARE = 0.8

#: 表达风格与它的几种说法。
#:
#: 两条设计约束，破了哪一条这份人口就测不出语义召回的价值：
#:
#: **自述里绝不出现风格名本身。** 一旦有人写"我是朋克风"，一句 `ILIKE '%朋克%'`
#: 就能召回，语义那一路就成了摆设。所以"野"这一档的人只会说"句子里得有点
#: 攻击性"，不会说"野"。
#:
#: **风格与技能、专业无关。** 抽风格不看专业——否则风格就能被结构化字段预测
#: 出来，先过滤再语义比较的分层也就没意义了。
#:
#: 权重是长尾的：多数人温和克制，"野"只有 6%。稀缺才有召回价值。
STYLE_VOICES: tuple[tuple[str, float, tuple[str, ...]], ...] = (
    (
        "野",
        0.06,
        (
            "写东西不爱端着，句子里得带点攻击性才舒服",
            "偏爱粗粝的表达，太干净的稿子我写不出来",
            "喜欢短句、狠话，看不惯那种四平八稳的腔调",
            "文风比较冲，甲方说过好几次太扎人",
        ),
    ),
    (
        "克制",
        0.26,
        (
            "习惯把话说短，能删的字一定删掉",
            "不喜欢用力过猛，留白比堆砌更有说服力",
            "写完总要再删一遍，形容词基本都会被我砍掉",
        ),
    ),
    (
        "严谨",
        0.20,
        (
            "每个数字都要有出处，没查过的话不敢写进去",
            "喜欢把论证链条摆完整，跳步会让我很不安",
            "做事按流程来，宁可慢一点也不想返工",
        ),
    ),
    (
        "诙谐",
        0.16,
        (
            "写什么都想埋个梗，正经不过三行",
            "喜欢用比喻和玩笑把干巴巴的东西讲活",
            "群里的沙雕表情包多半是我发的",
        ),
    ),
    (
        "温暖",
        0.20,
        (
            "在意别人读完是什么感受，语气会反复调",
            "喜欢写具体的人和小事，宏大叙事打动不了我",
            "组里有人不说话我会主动去问一句",
        ),
    ),
    (
        "商务",
        0.12,
        (
            "习惯先讲结论再讲理由，汇报口径要统一",
            "偏好正式的表达，场合不对的玩笑我不会开",
            "做过几次对外提案，知道甲方想听什么",
        ),
    ),
)

#: 做事节奏。和风格独立抽，让自述有两个互不相关的维度——
#: 只有一个维度的话，向量比较容易退化成在比同一句话。
WORK_RHYTHMS: tuple[str, ...] = (
    "习惯早定方案早收工，拖到最后一天会焦虑",
    "前松后紧，灵感通常在截止前一晚才来",
    "喜欢先做个粗糙版本出来再一起改",
    "开工前想把分工谈清楚，中途改需求会很难受",
    "线上沟通就够了，不太想为了对齐专门跑一趟",
    "更喜欢当面聊，隔着屏幕总觉得没说透",
)

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
    #: 自己写的一段话。**没有任何结构化字段装得下它**——语义召回就是为它存在的。
    self_intro: str = ""
    #: 这段话背后的风格档位。只用于**校验召回效果**，不入库、不参与匹配——
    #: 真实用户身上没有这个标签，拿它做匹配等于给仿真开后门。
    voice: str = ""


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


def fingerprint(population: Population) -> str:
    """一份人口的指纹。

    可复现性只有跨进程才有意义，所以这条不能靠"跑两次比一比"——
    要比就得比一个**写死在测试里的常量**。指纹变了说明生成器变了，
    那时候要么是有意改的（更新常量，并在提交信息里说清改了什么），
    要么是又漏进了一处进程相关的随机性。
    """
    payload = "|".join(
        f"{p.display_name}:{p.availability}:{','.join(sorted(p.skills))}:{p.zone}"
        for p in population.people
    )
    return blake2b(payload.encode(), digest_size=16).hexdigest()


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


def _slot_of(course: str) -> int:
    """一门课占哪个时段。

    **不能用内置 `hash()`。** Python 的字符串哈希每个进程加不同的盐，
    于是同一个种子在两次运行里会生成两份不同的课表——而"给定种子完全可复现"
    是这份人口存在的前提：仿真结论必须能被重跑验证，不然那些实测数字
    （四人组 45%、七倍富集）就只是某一次运行的巧合。

    这个洞藏了很久没被发现，因为可复现性测试是在**同一个进程内**跑两次
    `generate()` 比较——进程内盐相同，永远相等。现在那条测试改成比对
    一份写死的指纹。
    """
    return blake2b(course.encode(), digest_size=8).digest()[0] % WEEK_SLOTS


def _availability_from_courses(rng: random.Random, courses: list[str]) -> str:
    """课表决定空闲。同一门课的人被占掉同一批时段。"""
    busy = set()
    for course in courses:
        # 课程名决定它占哪个时段——同一门课对所有人占同一格。
        slot = _slot_of(course)
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


def _zone_for(rng: random.Random, major: str) -> str:
    """校区跟着院系走，留两成散在别处。

    这让技能和地点变得**相关**：设计学院在西校区，于是"缺个会调色的，
    在南校区"是真的会卡住的组合，而不是一个永远能凑上的假约束。
    """
    home = MAJOR_HOME_ZONE.get(major)
    if home and rng.random() < HOME_ZONE_SHARE:
        return home
    return rng.choice(CAMPUS_ZONES)


def _self_intro(rng: random.Random) -> tuple[str, str]:
    """抽一段自述，返回（自述, 风格档位）。

    **不看专业、不看技能。** 风格一旦能被结构化字段预测出来，
    先过滤再语义比较的分层就没有意义了。
    """
    voice = _weighted_choice(rng, tuple((name, w) for name, w, _ in STYLE_VOICES))
    lines = next(ls for name, _, ls in STYLE_VOICES if name == voice)
    return f"{rng.choice(lines)}。{rng.choice(WORK_RHYTHMS)}。", voice


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
        intro, voice = _self_intro(rng)

        person = SyntheticPerson(
            id=uuid4(),
            display_name=(
                f"{rng.choice(_SURNAMES)}{rng.choice(_GIVEN)}{rng.choice(_GIVEN)}"
            ),
            major=major,
            year=year,
            zone=_zone_for(rng, major),
            skills=_skills_for(rng, major),
            availability=_availability_from_courses(rng, courses),
            affiliations=tuple(courses + clubs),
            history_tier=_history_tier(rng),
            self_intro=intro,
            voice=voice,
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
