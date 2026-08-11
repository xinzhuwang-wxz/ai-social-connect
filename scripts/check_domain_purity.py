#!/usr/bin/env python3
"""领域核心纯度检查。

守两条架构规则，任一违反即退出码 1：

1. **领域核心不得直接读系统时钟。** 时间必须经 `Clock` 端口注入，否则仿真
   无法快进、测试只能靠 sleep。
2. **领域核心不得 import 任何第三方 SDK。** 只允许标准库与 `cofield.domain`
   自身。第三方类型一旦渗进领域签名，"换掉一个适配器不触及领域测试"这条就废了。

用 AST 而不是 grep：`# datetime.now()` 出现在注释里不该报错，
`from datetime import datetime as dt; dt.now()` 也不该漏掉。
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

DOMAIN_ROOT = Path(__file__).resolve().parents[1] / "apps/api/src/cofield/domain"
OWN_PACKAGE_PREFIX = "cofield.domain"

# 读系统时钟的调用。键是被调用的属性名，值是它必须来自的模块/类。
FORBIDDEN_CALLS: dict[str, tuple[str, ...]] = {
    "now": ("datetime", "date"),
    "utcnow": ("datetime",),
    "today": ("date", "datetime"),
    "time": ("time",),
    "monotonic": ("time",),
    "time_ns": ("time",),
}


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    rule: str
    detail: str

    def render(self, root: Path) -> str:
        rel = self.path.relative_to(root)
        return f"  {rel}:{self.line}  [{self.rule}] {self.detail}"


class DomainVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.violations: list[Violation] = []
        # 记录 `from datetime import datetime as dt` 这类别名
        self._aliases: dict[str, str] = {}

    # --- imports ---

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".")[0]
            self._aliases[alias.asname or root] = root
            self._check_module(root, node.lineno, alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:  # 相对导入，必在包内
            self.generic_visit(node)
            return
        module = node.module or ""
        root = module.split(".")[0]
        for alias in node.names:
            self._aliases[alias.asname or alias.name] = root
        self._check_module(root, node.lineno, module)
        self.generic_visit(node)

    def _check_module(self, root: str, lineno: int, full: str) -> None:
        if full.startswith(OWN_PACKAGE_PREFIX):
            return
        if root == "cofield":
            self.violations.append(
                Violation(
                    self.path,
                    lineno,
                    "domain-imports-outward",
                    f"领域核心不能依赖外圈：{full}",
                )
            )
            return
        if root in sys.stdlib_module_names:
            return
        self.violations.append(
            Violation(
                self.path,
                lineno,
                "domain-imports-third-party",
                f"领域核心不能 import 第三方库：{full}",
            )
        )

    # --- clock reads ---

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in FORBIDDEN_CALLS:
            owner = _root_name(func.value)
            if owner is not None:
                origin = self._aliases.get(owner, owner)
                if origin in FORBIDDEN_CALLS[func.attr]:
                    self.violations.append(
                        Violation(
                            self.path,
                            node.lineno,
                            "domain-reads-clock",
                            f"领域核心不能直接读时钟：{owner}.{func.attr}() —— 用 Clock 端口",
                        )
                    )
        self.generic_visit(node)


def _root_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def scan(domain_root: Path) -> list[Violation]:
    violations: list[Violation] = []
    for path in sorted(domain_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = DomainVisitor(path)
        visitor.visit(tree)
        violations.extend(visitor.violations)
    return violations


def main() -> int:
    if not DOMAIN_ROOT.exists():
        print(f"找不到领域核心目录：{DOMAIN_ROOT}", file=sys.stderr)
        return 2

    repo_root = DOMAIN_ROOT.parents[4]
    violations = scan(DOMAIN_ROOT)
    if not violations:
        count = len(list(DOMAIN_ROOT.rglob("*.py")))
        print(f"领域核心纯度检查通过（{count} 个文件）")
        return 0

    print(f"领域核心纯度检查失败，{len(violations)} 处违规：\n", file=sys.stderr)
    for v in violations:
        print(v.render(repo_root), file=sys.stderr)
    print(
        "\n时间请经 cofield.domain.ports.Clock 注入；第三方依赖请放在 adapters 层。",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
