import os
import sys
from typing import Literal, Optional

from together import Together
from tenacity import retry, stop_after_attempt, wait_random_exponential

from app.model.common import Model, thread_cost
from app.data_structures import FunctionCallIntent
import app.model.common as common


class TogetherModel(Model):
    _instances = {}

    def __new__(cls):
        if cls not in cls._instances:
            cls._instances[cls] = super().__new__(cls)
            cls._instances[cls]._initialized = False
        return cls._instances[cls]

    def __init__(
        self,
        name: str,
        max_output_token: int,
        cost_per_input: float,
        cost_per_output: float,
        parallel_tool_call: bool = False,
    ):
        if self._initialized:
            return
        super().__init__(name, cost_per_input, cost_per_output, parallel_tool_call)
        self.max_output_token = max_output_token
        self.client: Optional[Together] = None
        self._initialized = True

    def check_api_key(self) -> str:
        key = os.getenv("TOGETHER_API_KEY")
        if not key:
            print("Please set the TOGETHER_API_KEY environment variable.")
            sys.exit(1)
        return key

    def setup(self) -> None:
        if self.client is None:
            key = self.check_api_key()
            self.client = Together(api_key=key)

    def extract_resp_content(self, msg) -> str:
        return msg.content or ""

    def extract_resp_func_calls(self, msg) -> list[FunctionCallIntent]:
        return []  # Tool calling not supported via Together API

    @retry(wait=wait_random_exponential(min=30, max=60), stop=stop_after_attempt(3))
    def call(
        self,
        messages: list[dict],
        top_p: float = 1.0,
        tools: list[dict] | None = None,
        response_format: Literal["text", "json_object"] = "text",
        temperature: float | None = None,
        **kwargs,
    ) -> tuple[str, None, list[FunctionCallIntent], float, int, int]:
        if temperature is None:
            temperature = common.MODEL_TEMP

        self.setup()

        if response_format == "json_object":
            messages[-1]["content"] += "\nRespond only with valid JSON."

        response = self.client.chat.completions.create(
            model=self.name,
            messages=messages,
            max_tokens=self.max_output_token,
            temperature=temperature,
            top_p=top_p,
        )

        choice = response.choices[0]
        msg = choice.message
        content = self.extract_resp_content(msg)
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens
        cost = self.calc_cost(input_tokens, output_tokens)

        thread_cost.process_cost += cost
        thread_cost.process_input_tokens += input_tokens
        thread_cost.process_output_tokens += output_tokens

        return content, None, [], cost, input_tokens, output_tokens


class TogetherDeepSeekV3(TogetherModel):
    def __init__(self):
        super().__init__(
            name="deepseek-ai/DeepSeek-V3",
            max_output_token=4096,
            cost_per_input=0.000004,
            cost_per_output=0.000008,
            parallel_tool_call=False,
        )
        self.note = "DeepSeek‑V3 via Together API"
