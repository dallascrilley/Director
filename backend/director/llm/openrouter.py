import json
from enum import Enum

from pydantic import Field, field_validator, FieldValidationInfo
from pydantic_settings import SettingsConfigDict


from director.llm.base import BaseLLM, BaseLLMConfig, LLMResponse, LLMResponseStatus
from director.constants import (
    LLMType,
    EnvPrefix,
)


class OpenRouterChatModel(str, Enum):
    """Enum for OpenRouter Chat models - includes models from multiple providers"""

    # OpenAI models
    GPT4O = "openai/gpt-4o"
    GPT4O_MINI = "openai/gpt-4o-mini"
    O3_MINI = "openai/o3-mini"

    # Anthropic models
    CLAUDE_3_5_SONNET = "anthropic/claude-3.5-sonnet"
    CLAUDE_3_5_HAIKU = "anthropic/claude-3.5-haiku"
    CLAUDE_3_OPUS = "anthropic/claude-3-opus"

    # Google models
    GEMINI_2_5_PRO = "google/gemini-2.5-pro-preview-03-25"
    GEMINI_2_0_FLASH = "google/gemini-2.0-flash-001"

    # Meta models
    LLAMA_3_3_70B = "meta-llama/llama-3.3-70b-instruct"

    # DeepSeek
    DEEPSEEK_CHAT = "deepseek/deepseek-chat"
    DEEPSEEK_R1 = "deepseek/deepseek-r1"


class OpenRouterConfig(BaseLLMConfig):
    """OpenRouter Config - OpenRouter provides a unified API for multiple LLM providers"""

    model_config = SettingsConfigDict(
        env_prefix=EnvPrefix.OPENROUTER_,
        extra="ignore",
    )

    llm_type: str = LLMType.OPENROUTER
    api_key: str = ""
    api_base: str = "https://openrouter.ai/api/v1"
    chat_model: str = Field(default=OpenRouterChatModel.GPT4O)
    max_tokens: int = 4096

    @field_validator("api_key")
    @classmethod
    def validate_non_empty(cls, v, info: FieldValidationInfo):
        if not v:
            raise ValueError(
                f"{info.field_name} must not be empty. please set {EnvPrefix.OPENROUTER_.value}{info.field_name.upper()} environment variable."
            )
        return v


class OpenRouter(BaseLLM):
    """OpenRouter LLM implementation - uses OpenAI-compatible API"""

    def __init__(self, config: OpenRouterConfig = None):
        """
        :param config: OpenRouter Config
        """
        if config is None:
            config = OpenRouterConfig()
        super().__init__(config=config)
        try:
            import openai
        except ImportError:
            raise ImportError("Please install OpenAI python library.")

        self.client = openai.OpenAI(api_key=self.api_key, base_url=self.api_base)

    def init_langfuse(self):
        from langfuse.decorators import observe

        self.chat_completions = observe(name=type(self).__name__)(self.chat_completions)
        self.text_completions = observe(name=type(self).__name__)(self.text_completions)

    def _format_messages(self, messages: list):
        """Format the messages to the format that OpenAI expects."""
        formatted_messages = []
        for message in messages:
            if message["role"] == "assistant" and message.get("tool_calls"):
                formatted_messages.append(
                    {
                        "role": message["role"],
                        "content": message["content"],
                        "tool_calls": [
                            {
                                "id": tool_call["id"],
                                "function": {
                                    "name": tool_call["tool"]["name"],
                                    "arguments": json.dumps(
                                        tool_call["tool"]["arguments"]
                                    ),
                                },
                                "type": tool_call["type"],
                            }
                            for tool_call in message["tool_calls"]
                        ],
                    }
                )
            else:
                formatted_messages.append(message)
        return formatted_messages

    def _format_tools(self, tools: list):
        """Format the tools to the format that OpenAI expects.

        **Example**::

            [
                {
                    "type": "function",
                    "function": {
                        "name": "get_delivery_date",
                        "description": "Get the delivery date for a customer's order.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "order_id": {
                                    "type": "string",
                                    "description": "The customer's order ID."
                                }
                            },
                            "required": ["order_id"],
                            "additionalProperties": False
                        }
                    }
                }
            ]
        """
        formatted_tools = []
        for tool in tools:
            formatted_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["parameters"],
                    },
                    "strict": True,
                }
            )
        return formatted_tools

    def chat_completions(
        self, messages: list, tools: list = [], stop=None, response_format=None
    ):
        """Get completions for chat.

        docs: https://openrouter.ai/docs
        """
        params = {
            "model": self.chat_model,
            "messages": self._format_messages(messages),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "stop": stop,
            "timeout": self.timeout,
        }
        if tools:
            params["tools"] = self._format_tools(tools)
            params["tool_choice"] = "auto"

        if response_format:
            params["response_format"] = response_format

        try:
            response = self.client.chat.completions.create(**params)
        except Exception as e:
            print(f"Error: {e}")
            return LLMResponse(content=f"Error: {e}")

        return LLMResponse(
            content=response.choices[0].message.content or "",
            tool_calls=[
                {
                    "id": tool_call.id,
                    "tool": {
                        "name": tool_call.function.name,
                        "arguments": json.loads(tool_call.function.arguments),
                    },
                    "type": tool_call.type,
                }
                for tool_call in response.choices[0].message.tool_calls
            ]
            if response.choices[0].message.tool_calls
            else [],
            finish_reason=response.choices[0].finish_reason,
            send_tokens=response.usage.prompt_tokens,
            recv_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
            status=LLMResponseStatus.SUCCESS,
        )
