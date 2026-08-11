"""语义嵌入端口。

结构化 schema 覆盖硬约束，覆盖不了表达。「想找个写朋克风格文案的」
没有任何表单字段装得下——这一路靠向量。

端口不说明用什么模型。换模型不该触及领域测试，这是判断这条边界画得对
不对的标准。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class EmbeddingUnavailable(Exception):
    """嵌入服务不可用。

    调用方**必须降级为纯结构化召回**，不能让整条链路挂掉——
    语义是增强，不是前提。
    """


class Embedder(Protocol):
    #: 向量维度。写库时要和列定义对上，所以它是端口的一部分。
    dimensions: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """批量编码。顺序与输入一致。"""
        ...
