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
    model_name: str = os.getenv("GEMINI_MODEL", "gemma-3-12b-it"),
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
        sample = "Skip to content\nNavigation Menu\nPlatform\nSolutions\nResources\nOpen Source\nEnterprise\nPricing\nSearch or jump to...\nSign in\nSign up\nMona the Octocat, Copilot, and Ducky float jubilantly upward from behind the GitHub product demo accompanied by a purple glow and a scattering of stars.\nThe future of building happens together\n\nTools and trends evolve, but collaboration endures. With GitHub, developers, agents, and code come together on one platform.\n\nEnter your email\nSign up for GitHub\nTry GitHub Copilot free\nGitHub features\nA demonstration animation of a code editor using GitHub Copilot Chat, where the user requests GitHub Copilot to refactor duplicated logic and extract it into a reusable function for a given code snippet.\nCodePlanCollaborateAutomateSecure\n\nWrite, test, and fix code quickly with GitHub Copilot, from simple boilerplate to complex features.\n\nGitHub customers\nAccelerate your entire workflow\n\nFrom your first line of code to final deployment, GitHub provides AI and automation tools to help you build and ship better software faster.\n\nA Copilot chat window with the 'Ask' mode enabled. The user switches from 'Ask' mode to 'Agent' mode from a dropdown menu, then sends the prompt 'Update the website to allow searching for running races by name.' Copilot analyzes the codebase, then explains the required edits for three files before generating them. Copilot then confirms completion and summarizes the implemented changes for the new functionality allowing users to search races by name and view paginated, filtered results.\nYour AI partner everywhere. Copilot is ready to work with you at each step of the software development lifecycle.\nExplore GitHub Copilot\n\nDuolingo boosts developer speed by 25% with GitHub Copilot\n\nRead customer story\n\n2025 Gartner\u00ae Magic Quadrant\u2122 for AI Code Assistants\n\nRead industry report\nAutomate your path to production\n\nShip faster with secure, reliable CI/CD.\n\nExplore GitHub Actions\nCode instantly from anywhere\n\nLaunch a full, cloud-based development environment in seconds.\n\nExplore GitHub Codespaces\nKeep momentum on the go\n\nManage projects and assign tasks to Copilot, all from your mobile device.\n\nExplore GitHub Mobile\nShape your toolchain\n\nExtend your stack with apps, actions, and AI models.\n\nExplore GitHub Marketplace\nBuilt-in application security where found means fixed\n\nUse AI to find and fix vulnerabilities so your team can ship more secure software faster.\n\nApply fixes in seconds. Spend less time debugging and more time building features with Copilot Autofix.\nExplore GitHub Advanced Security\n\nSecurity debt, solved. Leverage security campaigns and Copilot Autofix to reduce application vulnerabilities.\n\nLearn about GitHub Code Security\n\nDependencies you can depend on. Update vulnerable dependencies with supported fixes for breaking changes.\n\nLearn about Dependabot\n\nYour secrets, your business. Detect, prevent, and remediate leaked secrets across your organization.\n\nLearn about GitHub Secret Protection\n\n70% MTTR reduction\nwith Copilot Autofix1\n\n8.3M secret leaks stopped\nin the past 12 months with push protection1\n\nWork together, achieve more\n\nFrom planning and discussion to code review, GitHub keeps your team\u2019s conversation and context next to your code.\n\nPlan with clarity. Organize everything from high-level roadmaps to everyday tasks.\nExplore GitHub Projects\n\u201c\nIt helps us onboard new software engineers and get them productive right away. We have all our source code, issues, and pull requests in one place... GitHub is a complete platform that frees us from menial tasks and enables us to do our best work.\nFabian Faulhaber\nApplication manager at Mercedes-Benz\nKeep track of your tasks\n\nCreate issues and manage projects with tools that adapt to your code.\n\nExplore GitHub Issues\nShare ideas and ask questions\n\nCreate space for open-ended conversations alongside your project.\n\nExplore GitHub Discussions\nReview code changes together\n\nAssign initial reviews to Copilot for greater speed and quality.\n\nExplore code review\nFund open source projects\n\nBecome an open source partner and support the tools and libraries that power your work.\n\nExplore GitHub Sponsors\nFrom startups to enterprises, GitHub scales with teams of any size in any industry.\nBy industryBy sizeBy use case\nTechnology\n\nFigma streamlines development and strengthens security\n\nRead customer story\nAutomotive\n\nMercedes-Benz standardizes source code and automates onboarding\n\nRead customer story\nFinancial services\n\nMercado Libre cuts coding time by 50%\n\nRead customer story\nExplore customer stories\nView all solutions\nA subtle purple glow fades in as Mona the Octocat, Copilot, and Ducky dramatically fall into place next to one another while gazing optimistically into the distance.\nMillions of developers and businesses call GitHub home\n\nWhether you\u2019re scaling your development process or just learning how to code, GitHub is where you belong. Join the world\u2019s most widely adopted developer platform to build the technologies that shape what\u2019s next.\n\nEnter your email\nSign up for GitHub\nTry GitHub Copilot free\nFootnotes\n\nGitHub internal customer data, 2025.\n\nSite-wide Links\nSubscribe to our developer newsletter\n\nGet tips, technical guides, and best practices. Twice a month.\n\nSubscribe\nPlatform\nFeatures\nEnterprise\nCopilot\nAI\nSecurity\nPricing\nTeam\nResources\nRoadmap\nCompare GitHub\nEcosystem\nDeveloper API\nPartners\nEducation\nGitHub CLI\nGitHub Desktop\nGitHub Mobile\nGitHub Marketplace\nMCP Registry\nSupport\nDocs\nCommunity Forum\nProfessional Services\nPremium Support\nSkills\nStatus\nContact GitHub\nCompany\nAbout\nWhy GitHub\nCustomer stories\nBlog\nThe ReadME Project\nCareers\nNewsroom\nInclusion\nSocial Impact\nShop\n\u00a9 2026 GitHub, Inc.\nTerms\nPrivacy (Updated 02/2024)\n02/2024\nSitemap\nWhat is Git?\nManage cookies\nDo not share my personal information\nGitHub on LinkedIn\nGitHub on Instagram\nGitHub on YouTube\nGitHub on X\nGitHub on TikTok\nGitHub on Twitch\nGitHub\u2019s organization on GitHub\n English"
        try:
            res = await verify_page_text("https://github.com",sample)
            print(json.dumps(res, indent=2))
        except Exception as e:
            print(f"Error: {e}")

    asyncio.run(test())