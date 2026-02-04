import os
import json
import logging
import asyncio
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

# LangChain Imports
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

# Specialized Verifiers
from loader import PageLoader
from url_verifier import URLVerifier
from layout_validator import LayoutValidator

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# --- Configuration ---
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# --- Agent System Prompt ---
SYSTEM_PROMPT = """
You are the "Antigravity QA Orchestrator," an advanced AI agent designed to ensure web application quality.
Your mission is to perform deep verification of web pages sequentially.

OPERATIONAL PROTOCOL:
1. DATA INGESTION: You receive raw page data from the 'Loader'.
2. URL VERIFICATION: You MUST first invoke the 'verify_url_tool' to check HTTP health, console errors, and load times.
3. TEXT VALIDATION: If the URL is healthy, you MUST then invoke the 'verify_text_tool' to ensure the page content matches its intended purpose.
4. SYNTHESIS: Finally, you provide a concise executive summary of the page's health.

BEHAVIORAL GUIDELINES:
- Be precise and objective.
- If a tool reports a 'FAIL', highlight it immediately.
- Use your internal reasoning to interpret tool outputs and explain the "Why" behind any failures.
"""

TEXT_ANALYSIS_PROMPT = """
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

# --- Tool Definitions ---

@tool
def verify_url_tool(page_data: Dict[str, Any]) -> str:
    """
    Analyzes the technical health of the page load.
    Checks: HTTP status, Redirects, Console Errors, and Load Speed.
    """
    print("\n[Tool Call] verify_url_tool activated...")
    verifier = URLVerifier()
    report = verifier.verify(
        url=page_data["url"], 
        final_url=page_data["final_url"], 
        http_status=page_data["http_status"], 
        status=page_data["status"], 
        navigation_time=page_data["navigation_time_seconds"], 
        load_time=page_data["load_time_seconds"], 
        error=page_data.get("error"), 
        console_errors=page_data.get("console_errors", [])
    )
    # Output to terminal for real-time visibility
    verifier.print_report(report)
    
    return json.dumps({
        "is_ok": report.is_ok,
        "final_url": report.final_url,
        "status_label": report.status_label,
        "issues_found": report.issues,
        "console_error_count": report.console_summary.get("errors", 0)
    })

@tool
async def verify_text_tool(page_data: Dict[str, Any]) -> str:
    """
    Uses AI to validate the textual content of the page.
    Checks: Content alignment, Inferred purpose, and quality.
    """
    print("\n[Tool Call] verify_text_tool (AI) activated...")
    
    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
        temperature=0,
        google_api_key=os.environ["GEMINI_API_KEY"],
    )
    
    visible_text = page_data.get("visible_text", "")
    if not visible_text:
        return json.dumps({"status": "FAIL", "reason": "Empty page text detected."})

    # Prepare analysis prompt
    prompt = TEXT_ANALYSIS_PROMPT.format(visible_text=visible_text) # Truncate for safety
    response = await llm.ainvoke([SystemMessage(content="You are a QA specialist."), HumanMessage(content=prompt)])
    print(response.content)
    # Extract JSON content
    raw_content = response.content.strip().replace("```json", "").replace("```", "").strip()
    return raw_content

@tool
def verify_layout_tool(page_data: Dict[str, Any]) -> str:
    """
    Analyzes the visual layout for bugs like overflows or small touch targets.
    Checks: Desktop and Mobile snapshots.
    """
    print("\n[Tool Call] verify_layout_tool activated...")
    validator = LayoutValidator()
    
    if page_data.get("layout_snapshot_desktop"):
        validator.validate_snapshot(page_data["layout_snapshot_desktop"], "desktop")
    if page_data.get("layout_snapshot_mobile"):
        validator.validate_snapshot(page_data["layout_snapshot_mobile"], "mobile")
    
    validator.print_detailed_report()
    return json.dumps(validator.generate_report())

# --- The AI Agent Orchestrator ---

class QAAgent:
    def __init__(self):
        self.tools = [verify_url_tool, verify_text_tool, verify_layout_tool]

    async def run(self, page_data: Dict[str, Any]):
        """
        Main execution loop for the Agent's autonomous process.
        """
        print(f"\n🤖 QAAgent: Activating for URL: {page_data.get('url')}")
        
        # --- Step 1: URL Verification ---
        url_results_json = verify_url_tool.invoke({"page_data": page_data})
        url_results = json.loads(url_results_json)
        
        # --- Step 2: Text Verification ---
        text_results_json = await verify_text_tool.ainvoke({"page_data": page_data})
        try:
            text_results = json.loads(text_results_json)
        except:
            text_results = {"status": "FAIL", "reason": "AI response was not valid JSON", "raw": text_results_json}

        # --- Step 3: Layout Verification ---
        layout_results_json = verify_layout_tool.invoke({"page_data": page_data})
        layout_results = json.loads(layout_results_json)

        # --- Step 4: Synthesis & Final Recommendation ---
        synthesis_input = f"""
        Page Scan Context:
        - URL Report: {url_results_json}
        - AI Text Report: {text_results_json}
        - Layout Report Summary: {json.dumps(layout_results.get('summary'))}
        
        Provide a final 'Executive Summary' (2 sentences max) describing the overall health of this page.
        """
        llm = ChatGoogleGenerativeAI(model=MODEL_NAME, temperature=0, google_api_key=os.environ["GEMINI_API_KEY"])
        summary_resp = await llm.ainvoke([SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=synthesis_input)])
        
        return {
            "url_report": url_results,
            "text_report": text_results,
            "layout_report": layout_results,
            "executive_summary": summary_resp.content
        }


# --- Main Entry Point ---

async def main():
    # 1. Initialize Loader
    loader = PageLoader()
    await loader.start()
    
    # 2. Define URL to test
    target_url = "https://practice.qabrains.com/"
    print(f"\n--- Initializing QA Pipeline for: {target_url} ---")
    
    # 3. Loader runs and returns data
    page_data = await loader.load(target_url)
    
    # 4. Agent takes over
    if page_data:
        agent = QAAgent()
        final_report = await agent.run(page_data)
        
        # Log final findings
        print("\n" + "#"*50)
        print("FINAL AGENT REPORT & RECOMMENDATION")
        print("#"*50)
        print(f"\nSUMMARY: {final_report['executive_summary']}")
        print(f"\nURL Status:    {final_report['url_report'].get('status_label')}")
        print(f"Text Status:   {final_report['text_report'].get('status')}")
        print(f"Layout Status: {final_report['layout_report'].get('status')}")
        print("#"*50 + "\n")

    await loader.stop()

if __name__ == "__main__":
    asyncio.run(main())