import os

from director.constants import LLMType

from director.llm.openai import OpenAI
from director.llm.anthropic import AnthropicAI
from director.llm.googleai import GoogleAI
from director.llm.videodb_proxy import VideoDBProxy
from director.llm.openrouter import OpenRouter


def get_default_llm():
    """Get default LLM"""

    openai = bool(os.getenv("OPENAI_API_KEY"))
    anthropic = bool(os.getenv("ANTHROPIC_API_KEY"))
    googleai = bool(os.getenv("GOOGLEAI_API_KEY"))
    openrouter = bool(os.getenv("OPENROUTER_API_KEY"))

    default_llm = os.getenv("DEFAULT_LLM")

    if default_llm == LLMType.OPENROUTER:
        return OpenRouter()
    if default_llm == LLMType.OPENAI:
        return OpenAI()
    if default_llm == LLMType.ANTHROPIC:
        return AnthropicAI()
    if default_llm == LLMType.GOOGLEAI:
        return GoogleAI()

    if openai:
        return OpenAI()
    if anthropic:
        return AnthropicAI()
    if googleai:
        return GoogleAI()
    if openrouter:
        return OpenRouter()
    return VideoDBProxy()
