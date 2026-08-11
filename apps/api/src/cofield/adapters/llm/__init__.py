"""生成式模型的适配器。

领域核心看不到这里的任何东西——它只认识 `domain/ports/composer.py` 的
`Composer` 协议。换模型、换服务商、换成录制回放，领域测试一条都不用改，
这是判断这条边界画得对不对的标准。
"""

from .cassette import Cassette, CassetteMiss
from .litellm_composer import DEFAULT_MODEL, LiteLLMComposer

__all__ = ["DEFAULT_MODEL", "Cassette", "CassetteMiss", "LiteLLMComposer"]
