# -*- coding: utf-8 -*-

from .http import (
    AiError,
    http_request,
    http_stream,
    normalize_base_url,
)
from .markdown import markdown_to_html
from .model_info import pretty_model_name
from .providers import (
    ADAPTER_CLASSES,
    BaseAdapter,
    CustomAdapter,
    DeepSeekAdapter,
    ErnieAdapter,
    OllamaAdapter,
    OpenAICompatibleAdapter,
    QwenAdapter,
    get_provider,
)
