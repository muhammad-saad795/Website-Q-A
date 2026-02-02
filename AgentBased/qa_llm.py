import os
import json
import logging
from typing import Dict, Any
import asyncio

from dotenv import load_dotenv
from google import genai                      # ← new import style
from google.genai.types import GenerationConfig
from google.api_core.exceptions import GoogleAPIError, DeadlineExceeded, ResourceExhausted

# Load .env file (do this once at module level)
load_dotenv()

# Reuse logger
logger = logging.getLogger(__name__)

# Universal QA Checklist Prompt
UNIVERSAL_QA_PROMPT_TEMPLATE = """
You are an expert website QA analyst.

Analyze the following visible page text and check for these common issues:

1. Is the page language consistent and professional? (no broken sentences, typos, lorem ipsum)
2. Are there clear headings and logical structure?
3. Is there a clear main message or call-to-action?
4. Are there any error messages, 404-like content, or "under construction"?
5. Are prices, contact info, or key claims realistic and complete?
6. Is navigation/menu text present and sensible?
7. Any repeated spam-like content or placeholders?

Visible Text:
{visible_text}

Respond **ONLY** in strict JSON format (no extra text, no markdown, no explanation outside JSON):
{{
  "overall_quality": "excellent/good/fair/poor/broken",
  "issues_found": ["list of problems or 'none'"],
  "passed_basic_qa": true,
  "summary": "One-sentence verdict"
}}
"""

class LLMVerificationError(Exception):
    """Custom exception for LLM verification failures."""
    pass

async def verify_page_text(
    url: str,
    visible_text: str,
    model_name: str = os.getenv("GEMINI_MODEL", "gemma-3-4b-it"),
    max_retries: int = 3,
    retry_delay: float = 2.0,
    text_truncate_limit: int = 100_000
) -> Dict[str, Any]:
    """
    Verifies visible page text using Gemini (new google-genai SDK) with universal QA checklist.
    """
    # Validate input
    if not isinstance(visible_text, str) or not visible_text.strip():
        raise ValueError("visible_text must be a non-empty string.")

    # Truncate if necessary
    if len(visible_text) > text_truncate_limit:
        visible_text = visible_text[:text_truncate_limit] + "\n[Text truncated for analysis]"
        logger.info(f"Truncated visible_text to {text_truncate_limit} chars.")

    # Get API key
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise LLMVerificationError("GEMINI_API_KEY not found in environment or .env file.")

    # Initialize client (new SDK style)
    client = genai.Client(api_key=api_key)

    # Prepare prompt
    prompt = UNIVERSAL_QA_PROMPT_TEMPLATE.format(visible_text=visible_text)

    # Retry configuration
    max_retries = 5
    base_delay = 5.0 # Start with 5 seconds for overloaded state
    
    # Retry loop
    for attempt in range(1, max_retries + 1):
        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model_name,
                contents=[prompt]
            )
            if not response or not response.text:
                raise LLMVerificationError("Empty response from Gemini.")

            # Parse JSON
            raw_text = response.text.strip()
            if raw_text.startswith("```json"):
                raw_text = raw_text.split("```json", 1)[1].split("```", 1)[0].strip()

            result = json.loads(raw_text)

            required_keys = {"overall_quality", "issues_found", "passed_basic_qa", "summary"}
            if not required_keys.issubset(result):
                raise ValueError(f"LLM response missing required keys. Keys found: {list(result.keys())}")
            result["url"] = url
            return result

        except (ResourceExhausted, GoogleAPIError, DeadlineExceeded) as e:
            # Exponential backoff for API errors (overloaded, too many requests)
            wait_time = base_delay * (2 ** (attempt - 1))
            logger.warning(f"Attempt {attempt}/{max_retries} - API error (possibly overloaded): {str(e)}. Retrying in {wait_time}s...")
            if attempt == max_retries:
                raise LLMVerificationError(f"Gemini verification failed after {max_retries} attempts: {str(e)}")
            await asyncio.sleep(wait_time)

        except (json.JSONDecodeError, ValueError) as e:
            # For parsing errors, retry once with a small delay or fail
            logger.warning(f"Attempt {attempt}/{max_retries} - Format error: {str(e)}")
            if attempt == max_retries:
                 raise LLMVerificationError(f"Gemini produced invalid JSON after {max_retries} attempts.")
            await asyncio.sleep(2.0)

    raise LLMVerificationError("Unexpected exit from retry loop.")

# Standalone test
if __name__ == "__main__":
    async def test():
        sample = """Logo
(Practice Site)
Home
QA Topics
Discussion
Tags
Jobs
Practice Site
About Us
Sign In
Demo Module

    User Authentication
        Login
        Registration
        Forgot Password
    Form Submission
    Drag and Drop List

Demo Site

    E-Commerce Site
    Booking Site

QA Practice Site

Learn and practice QA to master software testing, find bugs, and ensure quality. Build skills for reliable,
high-performing applications.
Failed to fetch component data
logo

QA Brains is the ultimate QA Community to exchange knowledge, seek advice, and engage in discussions that enhance Quality Assurance testers' skills and expertise.
QA Topics

    Web Testing
    Interview Questions
    Testing Framework
    See more

Quick Links

    Discussion
    About Us
    Terms & Conditions
    Privacy Policy

Follow Us
For Support
support@qabrains.com

© 2026 QA Brains | All Rights Reserved
"""
        try:
            res = await verify_page_text("https://practice.qabrains.com",sample)
            print(json.dumps(res, indent=2))
        except Exception as e:
            print(f"Error: {e}")

    asyncio.run(test())