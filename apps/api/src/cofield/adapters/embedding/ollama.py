"""本地 Ollama 嵌入。

选它是因为**零外部凭证**：产品的语义能力不该依赖一把可能没有的 API key。
默认 all-minilm（384 维），换成任何 Ollama 上的嵌入模型只改配置。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Sequence

from cofield.domain.ports.embedder import EmbeddingUnavailable

DEFAULT_ENDPOINT = "http://127.0.0.1:11434"
#: 三个本地模型在**真实任务上**实测之后选的，不是按名气选的。
#:
#: 任务：「想找个写朋克风格文案的」，从 499 个会写文案的人里把文风野的
#: 捞到前面（基线 7.0%）。
#:
#:     bge-m3                    1024 维   10.4s   top-20 命中 45%   6.4 倍
#:     all-minilm                 384 维    4.6s   top-20 命中 25%   3.6 倍
#:     paraphrase-multilingual    768 维    6.3s   top-20 命中 10%   1.4 倍
#:
#: paraphrase-multilingual 在这个任务上**比 all-minilm 还差**——多语言
#: 训练目标是句子改写等价，而我们要的是"文风相近"，两者不是一回事。
#: 这就是为什么这个选择必须实测：它和常识相反。
DEFAULT_MODEL = "bge-m3"
DEFAULT_DIMENSIONS = 1024


class OllamaEmbedder:
    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str = DEFAULT_MODEL,
        dimensions: int = DEFAULT_DIMENSIONS,
        timeout: float = 20.0,
    ) -> None:
        self.dimensions = dimensions
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._timeout = timeout

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = json.dumps({"model": self._model, "input": list(texts)}).encode()
        request = urllib.request.Request(
            f"{self._endpoint}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            # 上层必须降级为纯结构化召回——语义是增强，不是前提。
            raise EmbeddingUnavailable(f"嵌入服务不可用：{exc}") from exc

        vectors = body.get("embeddings")
        if not vectors or len(vectors) != len(texts):
            raise EmbeddingUnavailable("嵌入服务返回的数量与输入不符")
        if len(vectors[0]) != self.dimensions:
            raise EmbeddingUnavailable(
                f"维度不符：期望 {self.dimensions}，实际 {len(vectors[0])}"
            )
        return [[float(x) for x in v] for v in vectors]
