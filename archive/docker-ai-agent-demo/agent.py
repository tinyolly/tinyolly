# AI Agent Demo - Zero-Code Auto-Instrumentation
# NO OpenTelemetry imports needed - opentelemetry-instrument handles everything!

import time
import random
import os
import logging
from ollama import Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://ollama:11434")
client = Client(host=OLLAMA_HOST)

PROMPTS = [
    "Write a haiku about observability.",
    "Explain distributed tracing in one sentence.",
    "What is OpenTelemetry?",
    "Name three monitoring best practices.",
    "What makes a good dashboard?",
    "Describe the purpose of spans in tracing.",
]


def run_agent_workflow():
    prompt_text = random.choice(PROMPTS)
    logger.info(f"Calling Ollama with prompt: {prompt_text}")

    # This call is AUTO-INSTRUMENTED by opentelemetry-instrumentation-ollama
    # Spans with gen_ai.* attributes are created automatically!
    response = client.chat(
        model="tinyllama",
        messages=[{"role": "user", "content": prompt_text}]
    )

    content = response["message"]["content"]
    logger.info(f"Got response: {content[:100]}...")
    return content


if __name__ == "__main__":
    logger.info("Starting AI Agent Demo...")
    logger.info(f"Ollama host: {OLLAMA_HOST}")

    # Wait for Ollama to be ready
    time.sleep(10)

    logger.info("Starting agent loop...")
    while True:
        try:
            run_agent_workflow()
        except Exception as e:
            logger.error(f"Agent error: {e}")
        time.sleep(15)
