"""用户可见文案不得出现领域词汇。

`docs/07` §2.1 明确要求这条能被机器检查——"术语泄漏是可测的，
不应该靠 review 时凭感觉抓"。

## 黑名单从 CONTEXT.md 生成，不手抄

手抄的清单迟早和文档漂移：有人往术语表里加一个词，检查却不知道。
从原文抓的代价是正则要跟着格式走，但那个耦合是显式的、会立刻报错的，
比一份悄悄过期的清单好。

## 检查范围搞错了会制造噪音

`docs/07` §2.1 点名三类表面**不在范围内**：

1. 申诉、数据导出、争议处理——这些场景必须展示完整领域信息
2. 运营与安全后台——运营人员是领域词汇的合法使用者
3. 内部文档、PRD、代码注释、工程师视角的用户故事——本来就该用精确词汇

所以这里只扫**面向学生的可见文案**：前端组件里的中文字面量。
把代码注释也算进来，等于让工程师没法用精确的词讨论问题。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = ROOT / "CONTEXT.md"
WEB = ROOT / "apps" / "web"

#: 扫这些目录下的 tsx/ts。测试不扫——测试里出现禁词通常正是在断言它不出现。
SCAN_DIRS = ("app", "components")

#: 术语表里拆不出完整词的词根。它们不是"额外规则"，是同一张表的另一种写法：
#: CONTEXT.md 里写的是「意图信号」，而界面上出现「意图」两个字同样是泄漏。
ROOTS = (
    "意图", "主体", "切面", "共域", "漏斗", "召回", "求解", "约束",
    "提案", "授权", "撮合", "稳定性", "代理", "智能体", "凭证", "信封",
    "回声", "素材", "曝光公平", "policy_epoch",
)

#: 明确豁免的场景。见上面第 1、2 条——这些界面必须说清楚系统到底记了什么。
EXEMPT_MARKERS = ("data-vocabulary-exempt", "申诉", "数据导出")

#: 品牌用法。
#:
#: 「共域」既是一个领域概念，也是这个产品的名字。07 §2 的映射表自己写着
#: 「共域 → 我们的空间，**或直接就是项目名**」——所以产品名出现在标题栏、
#: 页脚、logo 旁边是对的，说「你的共域里有 3 条待办」才是错的。
#:
#: 用**精确整串**白名单而不是"含产品名就放行"：后者等于把这个词整个豁免掉，
#: 而那正是最容易被滥用的口子。每加一条都要能说出它是品牌位。
BRAND_LITERALS = frozenset(
    {
        "共域 · 找到人，把事做成",
        "共域 CoField",
        "共域",
    }
)

#: 中文片段。
#:
#: 第一版只扫带引号的字符串字面量——而 React 里绝大多数用户可见文案是
#: **JSX 文本节点**，`<p>你的共域里有 3 条待办</p>` 根本没有引号。
#: 那一版扫的是最不重要的那一半，用一个含泄漏的探针文件试过，一条都没抓到。
#:
#: 改成扫**所有中文串**。这在 .tsx 里是个可靠的启发：变量名、类型名、
#: 属性名都不会是中文，所以文件里出现的中文几乎全是要给人看的字。
_CHINESE_RUN = re.compile(r"[一-鿿][^\n]*?(?=[<>{}\"\'`;]|$)")
_LINE_COMMENT = re.compile(r"^\s*(//|/\*|\*)")


def domain_terms() -> set[str]:
    text = CONTEXT.read_text(encoding="utf-8")
    terms = set(re.findall(r"^\*\*([^*（\n]+)（", text, re.M))
    if len(terms) < 20:
        raise SystemExit(
            f"只从 {CONTEXT} 抓到 {len(terms)} 个术语——"
            "格式大概变了，这个检查现在什么都没在守"
        )
    return terms


def scan() -> list[tuple[Path, int, str, list[str]]]:
    banned = domain_terms() | set(ROOTS)
    leaks: list[tuple[Path, int, str, list[str]]] = []

    for directory in SCAN_DIRS:
        for path in sorted((WEB / directory).rglob("*.tsx")):
            source = path.read_text(encoding="utf-8")
            if any(marker in source for marker in EXEMPT_MARKERS):
                continue
            for number, line in enumerate(source.splitlines(), start=1):
                if _LINE_COMMENT.match(line):
                    continue
                for fragment in _CHINESE_RUN.findall(line):
                    text = fragment.strip()
                    if not text or text in BRAND_LITERALS:
                        continue
                    hit = sorted({term for term in banned if term in text})
                    if hit:
                        leaks.append((path, number, text, hit))
    return leaks


def main() -> int:
    if not WEB.exists():
        print("没有前端可扫")
        return 0

    leaks = scan()
    if not leaks:
        print("用户可见文案检查通过：没有领域词汇泄漏")
        return 0

    print("界面文案里出现了领域词汇——它们是代码和文档的语言，不是用户的语言：")
    print("（映射表见 docs/07-产品语言与界面原则.md §2）")
    for path, number, literal, hit in leaks:
        print(f"  {path.relative_to(ROOT)}:{number}  「{literal}」→ {hit}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
