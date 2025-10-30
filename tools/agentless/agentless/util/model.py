from abc import ABC, abstractmethod
from typing import List
import os
from agentless.util.api_requests import create_chatgpt_config, request_chatgpt_engine, create_anthropic_config, request_anthropic_engine, create_gemini_config, request_gemini_engine
from agentless.util.api_requests import create_together_config, request_together_engine 
from google.generativeai import GenerativeModel, configure
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import requests
from together import Together

class DecoderBase(ABC):
    def __init__(
        self,
        name: str,
        logger,
        batch_size: int = 1,
        temperature: float = 0.8,
        max_new_tokens: int = 1024,
    ) -> None:
        print("Initializing a decoder model: {} ...".format(name))
        self.name = name
        self.logger = logger
        self.batch_size = batch_size
        self.temperature = temperature
        self.max_new_tokens = max_new_tokens

    @abstractmethod
    def codegen(self, message: str, num_samples: int = 1) -> List[dict]:
        pass

    @abstractmethod
    def is_direct_completion(self) -> bool:
        pass

    def __repr__(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.name


class OpenAIChatDecoder(DecoderBase):
    def __init__(self, name: str, logger, **kwargs) -> None:
        super().__init__(name, logger, **kwargs)

    def codegen(self, message: str, num_samples: int = 1) -> List[dict]:
        if self.temperature == 0:
            assert num_samples == 1
        batch_size = min(self.batch_size, num_samples)

        config = create_chatgpt_config(
            message=message,
            max_tokens=self.max_new_tokens,
            temperature=self.temperature,
            batch_size=batch_size,
            model=self.name,
        )
        ret = request_chatgpt_engine(config, self.logger)
        if ret:
            responses = [choice.message.content for choice in ret.choices]
            completion_tokens = ret.usage.completion_tokens
            prompt_tokens = ret.usage.prompt_tokens
        else:
            responses = [""]
            completion_tokens = 0
            prompt_tokens = 0

        # The nice thing is, when we generate multiple samples from the same input (message),
        # the input tokens are only charged once according to openai API.
        # Therefore, we assume the request cost is only counted for the first sample.
        # More specifically, the `prompt_tokens` is for one input message,
        # and the `completion_tokens` is the sum of all returned completions.
        # Therefore, for the second and later samples, the cost is zero.
        trajs = [
            {
                "response": responses[0],
                "usage": {
                    "completion_tokens": completion_tokens,
                    "prompt_tokens": prompt_tokens,
                },
            }
        ]
        for response in responses[1:]:
            trajs.append(
                {
                    "response": response,
                    "usage": {
                        "completion_tokens": 0,
                        "prompt_tokens": 0,
                    },
                }
            )
        return trajs

    def is_direct_completion(self) -> bool:
        return False


class AnthropicChatDecoder(DecoderBase):
    def __init__(self, name: str, logger, **kwargs) -> None:
        super().__init__(name, logger, **kwargs)

    _STR_REPLACE_EDITOR_DESCRIPTION = """Custom editing tool for editing files
* State is persistent across command calls and discussions with the user

Notes for using the `str_replace` command:
* The `old_str` parameter should match EXACTLY one or more consecutive lines from the original file. Be mindful of whitespaces!
* If the `old_str` parameter is not unique in the file, the replacement will not be performed. Make sure to include enough context in `old_str` to make it unique
* The `new_str` parameter should contain the edited lines that should replace the `old_str`
"""

    _USER_REPLY_EDIT_MESSAGE = """File is successfully edited"""

    tools = [
        {
            "name": "str_replace_editor",
            "description": _STR_REPLACE_EDITOR_DESCRIPTION,
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "description": "Full path to file, e.g. `folder/file.py`.",
                        "type": "string",
                    },
                    "old_str": {
                        "description": "Required parameter containing the string in `path` to replace.",
                        "type": "string",
                    },
                    "new_str": {
                        "description": "Optional parameter containing the new string (if not given, no string will be added).",
                        "type": "string",
                    },
                },
                "required": ["path", "old_str"],
            },
        }
    ]

    MAX_CODEGEN_ITERATIONS = 10

    # specialized codegen with tool
    def codegen_w_tool(
        self, message: str, num_samples: int = 1, prompt_cache: bool = False
    ) -> List[dict]:
        def _build_response_and_extract(response, messages, iter):
            json_response = response.to_dict()

            contains_tool = False
            # formulate the messages
            json_response.pop("id")
            json_response.pop("model")
            json_response.pop("stop_reason")
            json_response.pop("stop_sequence")
            json_response.pop("type")
            json_response.pop("usage")

            messages.append(json_response)

            response_content = []

            for json_message in json_response["content"]:
                if json_message["type"] == "tool_use":
                    contains_tool = True
                    # each tool use requires a response
                    response_content.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": json_message["id"],
                            "content": self._USER_REPLY_EDIT_MESSAGE,
                        }
                    )

            if contains_tool:
                messages.append(
                    {
                        "role": "user",
                        "content": response_content,
                    }
                )
            else:
                if iter == 0:
                    # if the first iteration does not contain the tool, likely the model is doing some CoT for debugging
                    # append encouraging message
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Please generate editing commands to fix the issue",
                                }
                            ],
                        }
                    )
                    contains_tool = True

            return messages, contains_tool

        if self.temperature == 0:
            assert num_samples == 1

        trajs = []
        for _ in range(num_samples):
            self.logger.info(f" === Generating ====")
            # initialized the traj
            traj = {
                "response": [],
                "usage": {
                    "completion_tokens": 0,
                    "prompt_tokens": 0,
                    "cache_creation_token": 0,
                    "cache_read_input_tokens": 0,
                },
            }

            # create the initial config and messages
            messages = [
                {"role": "user", "content": [{"type": "text", "text": message}]}
            ]

            for iteration in range(self.MAX_CODEGEN_ITERATIONS):
                config = create_anthropic_config(
                    message=messages,
                    max_tokens=self.max_new_tokens,
                    temperature=self.temperature,
                    batch_size=1,
                    model=self.name,
                    tools=self.tools,
                )
                ret = request_anthropic_engine(
                    config,
                    self.logger,
                    prompt_cache=True,  # prompt cache should be always true as we at least should query twice
                )

                if ret:
                    # add the response to the traj
                    traj["response"].append([reply.to_dict() for reply in ret.content])

                    # pretty dump the response
                    for reply in ret.content:
                        self.logger.info(json.dumps(reply.to_dict(), indent=2))

                    # update the usage
                    traj["usage"]["completion_tokens"] += ret.usage.output_tokens
                    traj["usage"]["prompt_tokens"] += ret.usage.input_tokens
                    traj["usage"][
                        "cache_creation_token"
                    ] += ret.usage.cache_creation_input_tokens
                    traj["usage"][
                        "cache_read_input_tokens"
                    ] += ret.usage.cache_read_input_tokens

                    messages, contains_tool = _build_response_and_extract(
                        ret, messages, iteration
                    )

                    if not contains_tool:
                        break
                else:
                    assert (
                        False
                    ), "No response from the engine"  # this should not happen

            if ret:
                trajs.append(traj)
            else:
                trajs.append(
                    {
                        "response": "",
                        "usage": {
                            "completion_tokens": 0,
                            "prompt_tokens": 0,
                        },
                    }
                )

        return trajs

    def codegen(
        self, message: str, num_samples: int = 1, prompt_cache: bool = False
    ) -> List[dict]:
        if self.temperature == 0:
            assert num_samples == 1

        trajs = []
        for _ in range(num_samples):
            config = create_anthropic_config(
                message=message,
                max_tokens=self.max_new_tokens,
                temperature=self.temperature,
                batch_size=1,
                model=self.name,
            )
            ret = request_anthropic_engine(
                config, self.logger, prompt_cache=prompt_cache
            )

            if ret:
                trajs.append(
                    {
                        "response": ret.content[0].text,
                        "usage": {
                            "completion_tokens": ret.usage.output_tokens,
                            "prompt_tokens": ret.usage.input_tokens,
                            "cache_creation_token": 0
                            if not prompt_cache
                            else ret.usage.cache_creation_input_tokens,
                            "cache_read_input_tokens": 0
                            if not prompt_cache
                            else ret.usage.cache_read_input_tokens,
                        },
                    }
                )
            else:
                trajs.append(
                    {
                        "response": "",
                        "usage": {
                            "completion_tokens": 0,
                            "prompt_tokens": 0,
                        },
                    }
                )

        return trajs

    def is_direct_completion(self) -> bool:
        return False


class DeepSeekChatDecoder(DecoderBase):
    def __init__(self, name: str, logger, **kwargs) -> None:
        super().__init__(name, logger, **kwargs)

    def codegen(self, message: str, num_samples: int = 1) -> List[dict]:
        if self.temperature == 0:
            assert num_samples == 1

        trajs = []
        for _ in range(num_samples):
            config = create_chatgpt_config(
                message=message,
                max_tokens=self.max_new_tokens,
                temperature=self.temperature,
                batch_size=1,
                model=self.name,
            )
            ret = request_chatgpt_engine(
                config, self.logger, base_url="https://api.deepseek.com"
            )
            if ret:
                trajs.append(
                    {
                        "response": ret.choices[0].message.content,
                        "usage": {
                            "completion_tokens": ret.usage.completion_tokens,
                            "prompt_tokens": ret.usage.prompt_tokens,
                        },
                    }
                )
            else:
                trajs.append(
                    {
                        "response": "",
                        "usage": {
                            "completion_tokens": 0,
                            "prompt_tokens": 0,
                        },
                    }
                )

        return trajs

    def is_direct_completion(self) -> bool:
        return False
    
class GeminiChatDecoder(DecoderBase):
    def __init__(self, name: str, logger, api_key: str, **kwargs) -> None:
        super().__init__(name, logger, **kwargs)
        self.api_key = api_key
        configure(api_key=self.api_key)
        self.model = GenerativeModel(model_name=self.name)
        self.safety_settings = [
            {
                "category": HarmCategory.HARM_CATEGORY_HARASSMENT,
                "threshold": HarmBlockThreshold.BLOCK_NONE,
            },
            {
                "category": HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                "threshold": HarmBlockThreshold.BLOCK_NONE,
            },
            {
                "category": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                "threshold": HarmBlockThreshold.BLOCK_NONE,
            },
            {
                "category": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                "threshold": HarmBlockThreshold.BLOCK_NONE,
            },
        ]

    def codegen(self, message: str, num_samples: int = 1):
        if self.temperature == 0:
            assert num_samples == 1

        trajs = []
        generation_config = {
            "temperature": self.temperature,
            "max_output_tokens": self.max_new_tokens,
        }

        for _ in range(num_samples):
            try:
                self.logger.info(f"Sending prompt to Gemini model `{self.name}`")
                response = self.model.generate_content(
                    contents=message,
                    generation_config=generation_config,
                    safety_settings=self.safety_settings,
                )

                text_response = ""
                # Handle finish_reason and safely extract content
                if hasattr(response, "candidates") and response.candidates:
                    candidate = response.candidates[0]
                    finish_reason = getattr(candidate, "finish_reason", None)
                    
                    if finish_reason == "SAFETY":
                        self.logger.warning("Gemini blocked the generation due to safety filters.")
                    elif hasattr(candidate, "content") and hasattr(candidate.content, "parts"):
                        for part in candidate.content.parts:
                            if hasattr(part, "text"):
                                text_response += part.text

                trajs.append(
                    {
                        "response": text_response.strip(),
                        "usage": {
                            "completion_tokens": 0,
                            "prompt_tokens": 0,
                        },
                    }
                )

            except Exception as e:
                self.logger.error(f"Gemini generation failed: {e}")
                trajs.append(
                    {
                        "response": "",
                        "usage": {
                            "completion_tokens": 0,
                            "prompt_tokens": 0,
                        },
                    }
                )

        return trajs

    def is_direct_completion(self) -> bool:
        return False



class TogetherChatDecoder(DecoderBase):
    def __init__(self, name: str, logger, api_key: str, **kwargs) -> None:
        super().__init__(name, logger, **kwargs)
        self.api_key = api_key
        self.client = Together(api_key=self.api_key)

    def codegen(self, message: str, num_samples: int = 1) -> List[dict]:
        if self.temperature == 0:
            assert num_samples == 1

        trajs = []

        for _ in range(num_samples):
            try:
                self.logger.info(f"Sending prompt to Together AI model `{self.name}`")
                response = self.client.chat.completions.create(
                    model=self.name,
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": message}
                    ],
                    temperature=self.temperature,
                    max_tokens=self.max_new_tokens,
                    n=min(self.batch_size, num_samples)
                )

                choices = response.choices if hasattr(response, "choices") else []

                for choice in choices:
                    content = choice.message.content
                    trajs.append({
                        "response": content,
                        "usage": {
                            "completion_tokens": getattr(response.usage, "completion_tokens", 0),
                            "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                        }
                    })

            except Exception as e:
                self.logger.error(f"TogetherAI chat generation failed: {e}")
                trajs.append({
                    "response": "",
                    "usage": {
                        "completion_tokens": 0,
                        "prompt_tokens": 0,
                    },
                })

        return trajs

    def is_direct_completion(self) -> bool:
        return False
    


def make_model(
    model: str,
    backend: str,
    logger,
    batch_size: int = 1,
    max_tokens: int = 1024,
    temperature: float = 0.0,
):
    if backend == "openai":
        return OpenAIChatDecoder(
            name=model,
            logger=logger,
            batch_size=batch_size,
            max_new_tokens=max_tokens,
            temperature=temperature,
        )
    elif backend == "anthropic":
        return AnthropicChatDecoder(
            name=model,
            logger=logger,
            batch_size=batch_size,
            max_new_tokens=max_tokens,
            temperature=temperature,
        )
    elif backend == "deepseek":
        return DeepSeekChatDecoder(
            name=model,
            logger=logger,
            batch_size=batch_size,
            max_new_tokens=max_tokens,
            temperature=temperature,
        )
    elif backend == "google":
        return GeminiChatDecoder(
            name=model,
            logger=logger,
            api_key=os.environ["GOOGLE_API_KEY"],  # or pass explicitly
            batch_size=batch_size,
            max_new_tokens=max_tokens,
            temperature=temperature,
        )
    elif backend == "meta-llama" or backend == "deepseek-ai" or  backend == "Qwen":
        return TogetherChatDecoder(
            name=f"{backend}/{model}", 
            logger=logger,
            api_key=os.environ["TOGETHER_API_KEY"], 
            batch_size=batch_size,
            max_new_tokens=max_tokens,
            temperature=temperature,
        )
    else:
        raise NotImplementedError
