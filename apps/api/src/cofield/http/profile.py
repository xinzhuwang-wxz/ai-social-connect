"""我这边：我能做什么、我想参与什么、我是什么样的人。

## 这一面补的是产品里最大的一个洞

在它之前，一个真人只有**零条**路被别人找到：

- 漏斗第一段写死 `skills && needs`
- 而没有任何接口能写 `skills`
- 于是真人的这一列永远是空的，永远不进任何人的候选
- 合成主体又不能与真人同局（`formation.eligibility`）

**两个真人从来没有可能出现在同一个提案里。** 仿真里一切正常，因为合成
人口装载时直接把技能写进去了——这正是"每一片都测过、合起来走不动"的
又一例，而且是最贵的一例：它让这个产品最核心的那件事对真实用户不成立。

## 三个字段，三条不同的路

| 填的 | 走哪一路 | 谁认它 |
|---|---|---|
| 我能做的 | SQL 精确过滤 | 漏斗 + 求解器的角色覆盖 |
| 我想参与的 | SQL 精确过滤（或） | **只有漏斗**，求解器不认 |
| 我是什么样的人 | 语义召回 | 向量，装不进字段的都靠它 |

第二行那个「只有漏斗认」是刻意的：想参与不等于会做。放宽召回，不放宽承诺。

## 认不出来的词不拒收

用户会写「打杂」「帮忙跑腿」——词表里没有。整条拒收的代价是他填的其他
东西一起丢；静默丢掉的代价是他永远不知道为什么没人找他。

所以两样都不做：**收下，并且明说哪几项没被认出来**，同时告诉他这些话
写进下面那段自述里仍然算数——那一路本来就是为词表装不下的东西准备的。

## 为什么挂在 `/me` 下

和另外三个自我管理面同一条理由：系统里不存在供他人浏览的个人主页端点。
这一面写的是"我愿意被怎么找到"，读的人永远只能通过成局证明看到经本人
同意的那个切片。
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from cofield.adapters.persistence.semantic import PRINCIPAL, IndexableText
from cofield.domain.model.skills import MAJORS, SKILLS, normalise
from cofield.domain.ports.embedder import EmbeddingUnavailable
from cofield.http.deps import (
    CampusDep,
    ClockDep,
    IndexWriterDep,
    PrincipalDep,
    ReposDep,
)

router = APIRouter(tags=["profile"])

#: 常在的校区。空 = 哪个校区都行，硬过滤不排除他。
#: 和 `funnel._zone_of` 认的是同一批词——两处写两份的话，
#: 用户选了一个漏斗根本不认的校区，而界面上看不出任何异常。
ZONES: tuple[str, ...] = ("东校区", "西校区", "南校区")

SELF_INTRO_MAX = 500


class VocabularyOut(BaseModel):
    """界面上那些可点的词。

    **不能在前端硬编码。** 词表是封闭的，加一项要同时想清楚抽取器认不认得
    它的常见说法；两处各写一份，界面上就会出现一个匹配零个人的词。
    """

    skills: list[str]
    zones: list[str]
    majors: list[str]


class ProfileOut(BaseModel):
    display_name: str
    #: 这个名字还是系统给的占位。界面据此决定要不要先问他叫什么——
    #: **不要让界面自己去猜**（比如判断名字里有没有"同学"两个字）：
    #: 占位怎么生成是这一层的事，猜法迟早和生成规则对不上。
    named_self: bool = True
    #: 我能做的。求解器补洞只认这一项。
    skills: list[str]
    #: 我想参与的。它让"我不发起，但我想被叫上"这件事说得出口。
    open_to: list[str]
    self_intro: str | None = None
    zone: str | None = None
    #: 院系。**跨专业那条软目标只认它**——一个人不填，他就永远不会
    #: 因为"来自另一个院系"而被排进任何一个组。
    #: 将来它来自校园身份，不该由用户随手填；在那之前先让他自己说。
    major: str | None = None
    #: 这次提交里没被认出来的词。**不是错误**，是一句交代：
    #: 它们不会用来精确匹配，但写进自述里仍然算数。
    not_recognised: list[str] = Field(default_factory=list)


class ProfileIn(BaseModel):
    #: 我叫什么。空 = 这次不改名字，不是"改成空的"——
    #: 一个人不能把自己改成没有名字。
    display_name: str | None = Field(default=None, max_length=20)
    skills: list[str] = Field(default_factory=list)
    open_to: list[str] = Field(default_factory=list)
    self_intro: str | None = None
    zone: str | None = None
    major: str | None = None


def _normalise_all(raw: list[str]) -> tuple[list[str], list[str]]:
    """归一到词表，并把没认出来的原样带回。

    去重但**保序**：用户填的先后是他自己的排序，`set` 会把它打乱，
    而下一次打开这一屏看到自己填的东西换了位置，会以为系统改了什么。
    """
    keep: list[str] = []
    lost: list[str] = []
    for phrase in raw:
        text = phrase.strip()
        if not text:
            continue
        matched = normalise(text)
        if matched is None:
            if text not in lost:
                lost.append(text)
        elif matched not in keep:
            keep.append(matched)
    return keep, lost


@router.get("/vocabulary", response_model=VocabularyOut)
def vocabulary() -> VocabularyOut:
    return VocabularyOut(
        skills=sorted(SKILLS), zones=list(ZONES), majors=list(MAJORS)
    )


@router.get("/me/profile", response_model=ProfileOut)
def read(me: PrincipalDep, repos: ReposDep) -> ProfileOut:
    """我这边现在是什么样。

    身份第一次出现时 `get_repositories` 已经把行建好了，所以这里不会
    遇到"人不存在"——那一步放在依赖里而不是每个端点各自记得做。
    """
    principal = repos.principals.get(me)
    assert principal is not None  # noqa: S101 - JIT 供给保证它存在
    return ProfileOut(
        display_name=principal.display_name,
        named_self=repos.principals.has_named_self(me),
        skills=list(principal.skills),
        open_to=list(principal.open_to),
        self_intro=principal.self_intro,
        zone=principal.zone,
        major=principal.major,
    )


@router.put("/me/profile", response_model=ProfileOut)
def write(
    body: ProfileIn,
    me: PrincipalDep,
    repos: ReposDep,
    campus: CampusDep,
    clock: ClockDep,
    index: IndexWriterDep,
) -> ProfileOut:
    """改写我这边。整份覆盖，不是追加——"我不再想参与拍摄了"必须说得出口。"""
    skills, lost_skills = _normalise_all(body.skills)
    open_to, lost_open = _normalise_all(body.open_to)
    intro = (body.self_intro or "").strip()[:SELF_INTRO_MAX] or None
    zone = body.zone if body.zone in ZONES else None
    major = body.major if body.major in MAJORS else None

    # 起名单独走一步：它和"我能做什么"不是同一类东西——
    # 名字是身份，技能是这次能不能被找到。空着表示这次不改名，
    # **不是改成空的**：一个人不能把自己改成没有名字。
    named = (body.display_name or "").strip()
    if named:
        repos.principals.name_self(me, named)

    saved = repos.principals.describe(
        me,
        skills=skills,
        open_to=open_to,
        self_intro=intro,
        zone=zone,
        major=major,
    )

    # 自述进语义索引。**写不进去不算保存失败**——语义是增强不是前提，
    # 而"因为一个嵌入服务连不上，所以你填的东西没存下来"是最难解释的
    # 一种失败。索引可以事后补，用户填的这一次补不回来。
    if index is not None:
        try:
            if intro:
                index.index(
                    [IndexableText(subject_id=me, text=intro)],
                    subject_kind=PRINCIPAL,
                    campus_id=campus,
                    now=clock.now(),
                )
            else:
                # 清空自述 = 撤回这段话的露出，索引里那一行就该消失。
                index.forget(subject_kind=PRINCIPAL, subject_id=me)
        except EmbeddingUnavailable:
            pass

    lost = lost_skills + [w for w in lost_open if w not in lost_skills]
    return ProfileOut(
        display_name=saved.display_name,
        named_self=repos.principals.has_named_self(me),
        skills=list(saved.skills),
        open_to=list(saved.open_to),
        self_intro=saved.self_intro,
        zone=saved.zone,
        major=saved.major,
        not_recognised=lost,
    )


__all__ = ["ZONES", "router"]
