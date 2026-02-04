import os
import logging
import json
from typing import Dict, Any

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

# Load env
load_dotenv()

logger = logging.getLogger(__name__)

PROMPT = """
You are a website content evaluator.

Your ONLY task:
Determine whether the visible page text MATCHES what the page is supposed to say.

Step 1 — Infer the page's intended purpose
- Use headings, labels, and dominant keywords only.
- Examples: registration page, login page, landing page, documentation, blog, pricing page.

Step 2 — Evaluate content alignment
Check whether the text:
- Contains the expected information for that page type
- Avoids unrelated or contradictory content
- Is not placeholder, demo, or filler text

OUTPUT FORMAT (STRICT JSON ONLY):

{{
  "status": "PASS | FAIL",
  "inferred_page_type": "short label",
  "alignment": "MATCH | PARTIAL_MATCH | MISMATCH",
  "reason": "1–2 factual sentences explaining the decision"
}}

RULES:
- Do NOT evaluate grammar, UX, or design unless it directly affects alignment.
- Do NOT suggest fixes.
- Do NOT assume missing content.
- Be concise.
- No markdown.
- No extra fields.

Visible page text:
{visible_text}
"""


async def verify_page_text(
    url: str,
    visible_text: str,
    model_name: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    text_truncate_limit: int = 100_000,
) -> Dict[str, Any]:

    if not visible_text or not isinstance(visible_text, str):
        raise ValueError("visible_text must be a non-empty string")

    if len(visible_text) > text_truncate_limit:
        visible_text = visible_text[:text_truncate_limit]

    llm = ChatGoogleGenerativeAI(
        model=model_name,
        temperature=0,
        google_api_key=os.environ["GEMINI_API_KEY"],
    )

    prompt = PROMPT.format(visible_text=visible_text)

    response = await llm.ainvoke([HumanMessage(content=prompt)])

    return {
        "url": url,
        "analysis": response.content,
    }



if __name__ == "__main__":
    async def test():
        sample = """
                 hello world
        """
        try:
            res = await verify_page_text("https://practice.qabrains.com",sample)
            print(json.dumps(res, indent=2))
        except Exception as e:
            print(f"Error: {e}")

    asyncio.run(test())