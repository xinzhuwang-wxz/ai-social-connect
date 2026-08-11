#!/usr/bin/env python3
"""导出 OpenAPI 契约。

前端类型由这份文件生成，**任何一层都不手写类型**。CI 里跑一遍再比对
git 状态：契约变了却没重新生成前端类型，就在这里失败，而不是等到联调。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api/src"))

from cofield.http.app import create_app  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "artifacts/openapi.json"


def main() -> int:
    spec = create_app().openapi()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"契约已导出：{OUT}（{len(spec['paths'])} 条路径）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
