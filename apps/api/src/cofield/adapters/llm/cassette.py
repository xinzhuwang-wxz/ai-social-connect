"""录制回放：让 CI 不用凭证、不花钱、不看运气，也不用假货。

## 这不是 mock

"不用 mock/stub"是这个项目的红线，唯一被替换的是"人"。但 CI 里调真模型
有三个问题：要凭证、不确定、要钱。

磁带是这两者之间唯一诚实的解：**录一次真模型的真输出存下来，CI 回放。**
回放的内容是真的模型写的，这和手写一段假响应的区别不是程度，是性质——
手写的假货只会说我们以为模型会说的话，而那恰恰是最容易自欺的地方。

## 三种模式，默认是最安全的那个

- `replay`（默认）：只读磁带。**未命中就失败**，不静默穿透去调真模型——
  静默穿透会让 CI 在某次改动之后偷偷开始花钱，而且没人会发现。
- `record`：未命中就真调用并写盘。本地跑一次，把磁带提交上去。
- `off`：直接透传。只在手工调试时用。

## 键里为什么必须有模型名

换了模型就该重新录。沿用旧磁带等于用 A 模型的输出去验证 B 模型的行为，
那样"换模型不触及领域测试"这句话就成了假的——它之所以成立，
是因为领域测试根本不关心模型说了什么，而不是因为模型说的话恰好一样。
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from pathlib import Path

from cofield.domain.ports.composer import (
    Composer,
    ComposerUnavailable,
    Draft,
    DraftKind,
)

MODE_ENV = "COFIELD_LLM_MODE"
DIR_ENV = "COFIELD_LLM_CASSETTES"

DEFAULT_DIR = Path(__file__).resolve().parents[4] / "tests" / "cassettes"


class CassetteMiss(ComposerUnavailable):
    """回放模式下磁带里没有这一条。

    继承 `ComposerUnavailable` 是刻意的：调用方本来就必须处理起草不可用，
    多一种子类不会让它多写一个分支。但类型不同，所以"磁带缺了"和
    "服务挂了"在日志里分得清。
    """


def _key(
    kind: DraftKind,
    model: str,
    instruction: str,
    facts: Sequence[str],
    max_chars: int,
) -> str:
    payload = json.dumps(
        {
            "kind": kind.value,
            "model": model,
            "instruction": instruction,
            "facts": list(facts),
            "max_chars": max_chars,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


class Cassette:
    """包在任何 `Composer` 外面。"""

    def __init__(
        self,
        inner: Composer,
        *,
        directory: Path | None = None,
        mode: str | None = None,
    ) -> None:
        self._inner = inner
        self._dir = directory or Path(os.environ.get(DIR_ENV, DEFAULT_DIR))
        self._mode = mode or os.environ.get(MODE_ENV, "replay")

    @property
    def mode(self) -> str:
        return self._mode

    def draft(
        self,
        kind: DraftKind,
        *,
        facts: Sequence[str],
        instruction: str,
        max_chars: int = 200,
    ) -> Draft:
        if self._mode == "off":
            return self._inner.draft(
                kind, facts=facts, instruction=instruction, max_chars=max_chars
            )

        model = getattr(self._inner, "model", "unknown")
        key = _key(kind, model, instruction, list(facts), max_chars)
        path = self._dir / f"{key}.json"

        if path.exists():
            stored = json.loads(path.read_text(encoding="utf-8"))
            return Draft(
                text=stored["text"],
                model=stored["model"],
                grounded_in=tuple(stored["grounded_in"]),
                # 如实标记。混在一起会让"这次真的调了模型吗"无从判断。
                replayed=True,
            )

        if self._mode == "replay":
            raise CassetteMiss(
                f"磁带里没有 {key}（{kind.value}）。"
                f"本地用 {MODE_ENV}=record 跑一次再提交磁带。"
            )

        draft = self._inner.draft(
            kind, facts=facts, instruction=instruction, max_chars=max_chars
        )
        self._dir.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "kind": kind.value,
                    "model": draft.model,
                    "instruction": instruction,
                    "facts": list(facts),
                    "max_chars": max_chars,
                    "text": draft.text,
                    "grounded_in": list(draft.grounded_in),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return draft
