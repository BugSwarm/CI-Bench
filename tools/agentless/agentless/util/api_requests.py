import time
from typing import Dict, Union
import os
import openai
import anthropic
import tiktoken


def num_tokens_from_messages(message, model="gpt-3.5-turbo-0301"):
    """Returns the number of tokens used by a list of messages."""
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    if isinstance(message, list):
        # use last message.
        num_tokens = len(encoding.encode(message[0]["content"]))
    else:
        num_tokens = len(encoding.encode(message))
    return num_tokens


def create_chatgpt_config(
    message: Union[str, list],
    max_tokens: int,
    temperature: float = 1,
    batch_size: int = 1,
    system_message: str = "You are a helpful assistant.",
    model: str = "gpt-3.5-turbo",
) -> Dict:
    if isinstance(message, list):
        config = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "n": batch_size,
            "messages": [{"role": "system", "content": system_message}] + message,
        }
    else:
        config = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "n": batch_size,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": message},
            ],
        }
    return config


def handler(signum, frame):
    # swallow signum and frame
    raise Exception("end of time")


def request_chatgpt_engine(config, logger, base_url=None, max_retries=40, timeout=100):
    ret = None
    retries = 0

    client = openai.OpenAI(base_url=base_url)

    while ret is None and retries < max_retries:
        try:
            # Attempt to get the completion
            logger.info("Creating API request")

            ret = client.chat.completions.create(**config)

        except openai.OpenAIError as e:
            if isinstance(e, openai.BadRequestError):
                logger.info("Request invalid")
                print(e)
                logger.info(e)
                raise Exception("Invalid API Request")
            elif isinstance(e, openai.RateLimitError):
                print("Rate limit exceeded. Waiting...")
                logger.info("Rate limit exceeded. Waiting...")
                print(e)
                logger.info(e)
                time.sleep(5)
            elif isinstance(e, openai.APIConnectionError):
                print("API connection error. Waiting...")
                logger.info("API connection error. Waiting...")
                print(e)
                logger.info(e)
                time.sleep(5)
            else:
                print("Unknown error. Waiting...")
                logger.info("Unknown error. Waiting...")
                print(e)
                logger.info(e)
                time.sleep(1)

        retries += 1

    logger.info(f"API response {ret}")
    return ret


def create_anthropic_config(
    message: str,
    max_tokens: int,
    temperature: float = 1,
    batch_size: int = 1,
    system_message: str = "You are a helpful assistant.",
    model: str = "claude-2.1",
    tools: list = None,
) -> Dict:
    if isinstance(message, list):
        config = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": message,
        }
    else:
        config = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": message}]},
            ],
        }

    if tools:
        config["tools"] = tools

    return config


def request_anthropic_engine(
    config, logger, max_retries=40, timeout=500, prompt_cache=False
):
    ret = None
    retries = 0

    client = anthropic.Anthropic()

    while ret is None and retries < max_retries:
        try:
            start_time = time.time()
            if prompt_cache:
                # following best practice to cache mainly the reused content at the beginning
                # this includes any tools, system messages (which is already handled since we try to cache the first message)
                config["messages"][0]["content"][0]["cache_control"] = {
                    "type": "ephemeral"
                }
                ret = client.beta.prompt_caching.messages.create(**config)
            else:
                ret = client.messages.create(**config)
        except Exception as e:
            logger.error("Unknown error. Waiting...", exc_info=True)
            # Check if the timeout has been exceeded
            if time.time() - start_time >= timeout:
                logger.warning("Request timed out. Retrying...")
            else:
                logger.warning("Retrying after an unknown error...")
            time.sleep(10 * retries)
        retries += 1

    return ret

def create_gemini_config(
    message: Union[str, list],
    system_message: str = "You are a helpful assistant.",
    temperature: float = 1.0,
    max_tokens: int = 1024,
    model: str = "gemini-1.5-pro-latest",
) -> Dict:
    if isinstance(message, list):
        chat_text = f"{system_message}\n"
        for m in message:
            chat_text += f"{m.get('role', 'user').upper()}: {m['content']}\n"
    else:
        chat_text = f"{system_message}\nUSER: {message}"

    return {
        "model": model,
        "prompt": chat_text,
        "generation_config": {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
    }

def request_gemini_engine(config, logger, api_key: str, max_retries: int = 10, timeout: int = 60):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(config["model"])
    retries = 0

    while retries < max_retries:
        try:
            logger.info("Sending Gemini request...")
            response = model.generate_content(
                config["prompt"],
                generation_config=config["generation_config"]
            )
            logger.info("Gemini response received.")
            return response
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            time.sleep(2 * (retries + 1))
            retries += 1

    raise RuntimeError("Gemini API failed after retries.")

def create_together_config(
    message: Union[str, list],
    max_tokens: int,
    temperature: float = 1.0,
    batch_size: int = 1,
    model: str = "togethercomputer/llama-2-70b-chat"
) -> Dict:
    if isinstance(message, list):
        # Convert to prompt string
        prompt = "\n".join([m["content"] for m in message if m["role"] == "user"])
    else:
        prompt = message

    config = {
        "model": model,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": 0.9,
        "top_k": 50,
        "repetition_penalty": 1.0,
        "n": batch_size,
    }

    return config


def request_together_engine(config, logger, api_key, max_retries=10):
    url = "https://api.together.xyz/v1/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    for attempt in range(max_retries):
        try:
            logger.info("Sending request to Together API")
            response = requests.post(url, headers=headers, json=config)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.warning(f"Attempt {attempt + 1}/{max_retries} failed: {e}")
            time.sleep(min(2 ** attempt, 60))

    logger.error("All retries to Together API failed.")
    return None
