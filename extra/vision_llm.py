import os
import json
import logging
import asyncio
import base64
from typing import Dict, Any
from pathlib import Path

from dotenv import load_dotenv
from langchain_ollama import ChatOllama  # For multimodal/vision
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.runnables import RunnablePassthrough

# Load .env
load_dotenv()

logger = logging.getLogger(__name__)

# Vision Layout Prompt
VISION_LAYOUT_PROMPT = ChatPromptTemplate.from_template("""
Analyze this full-page screenshot for layout breakage.

Flag if broken based on:
- Overlaps / clipping / text overflow
- Misalignment / bad spacing
- Collapsed or hidden critical sections
- Off-screen elements
- General visual bugs

Respond ONLY JSON:
{{
  "is_broken": true/false,
  "issues": ["list or 'none'"],
  "summary": "1-2 sentence verdict"
}}
""")

class LLMVerificationError(Exception):
    pass

def get_vision_chain(model_name: str = os.getenv("LANGCHAIN_VISION_MODEL", "llava-phi3:latest")):
    """
    Creates LangChain chain for vision/layout analysis.
    Easy switch: Change to ChatOpenAI(model="gpt-4o") for cloud, etc.
    """
    llm = ChatOllama(model=model_name, temperature=0.2)
    
    parser = JsonOutputParser()
    
    # Chain: Prompt → LLM → Parse JSON
    chain = (
        VISION_LAYOUT_PROMPT
        | llm
        | parser
    )
    
    return chain

async def verify_layout_vision(
    screenshot_path: str | Path,
    model_name: str = os.getenv("LANGCHAIN_VISION_MODEL", "llava-phi3"),
    max_retries: int = 3,
    retry_delay: float = 2.0
) -> Dict[str, Any]:
    """
    Analyzes screenshot for layout issues using local Ollama + LangChain.
    """
    screenshot_path = Path(screenshot_path)
    if not screenshot_path.exists():
        raise ValueError("Screenshot file not found.")
    
    # Prepare base64 image
    with open(screenshot_path, "rb") as f:
        img_base64 = base64.b64encode(f.read()).decode("utf-8")
    
    chain = get_vision_chain(model_name)
    
    for attempt in range(1, max_retries + 1):
        try:
            # Invoke with image (Ollama/ChatOllama supports multimodal input)
            result = await chain.ainvoke({
                "image": img_base64  # Passed to model as multimodal content
            })
            return result
        except Exception as e:
            logger.warning(f"Attempt {attempt} failed: {e}")
            if attempt == max_retries:
                raise LLMVerificationError(f"Failed after {max_retries} attempts: {e}")
            await asyncio.sleep(retry_delay * attempt)

# Standalone test
if __name__ == "__main__":
    async def test():
        sample_ss = "path/to/screenshot.png"  # Replace with real path
        try:
            result = await verify_layout_vision("/home/ali/Downloads/Website QA/screenshots/8f866035_desktop.png")
            print(json.dumps(result, indent=2))
        except Exception as e:
            print(f"Error: {e}")

    asyncio.run(test())