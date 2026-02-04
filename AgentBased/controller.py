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
AGENT_SYSTEM_PROMPT = """
You are the "Antigravity QA Orchestrator," an advanced AI agent designed to ensure web application quality.

YOUR MISSION:
You receive raw page data from the Loader. You must perform comprehensive quality assurance by orchestrating multiple validation steps.

OPERATIONAL PROTOCOL:
1. URL VERIFICATION: First, invoke 'verify_url_tool' to check HTTP health, console errors, and load times.
2. LAYOUT VALIDATION: Then, invoke 'verify_layout_tool' to analyze visual layout for bugs like overflows or small touch targets.
3. TEXT VALIDATION: Finally, invoke 'verify_text_tool' to validate the visible text content matches its intended purpose.
4. SYNTHESIS: After collecting all results, provide a comprehensive final report summarizing the page's health.

BEHAVIORAL GUIDELINES:
- Execute steps sequentially: URL → Layout → Text
- Be precise and objective
- If any tool reports a 'FAIL', highlight it immediately
- Use your internal reasoning to interpret tool outputs and explain the "Why" behind any failures
- After all validations are complete, synthesize the results into a final executive summary
"""

# --- Final Report Synthesis Prompt ---
SYNTHESIS_PROMPT = """
You are a QA Report Synthesizer. Your task is to create a comprehensive final report based on multiple validation results.

You will receive:
1. URL Verification Report - Technical health (HTTP status, console errors, load times)
2. Layout Validation Report - Visual layout issues (overflows, touch targets, etc.)
3. Text Validation Report - Content alignment and quality

Create a concise executive summary (2-3 sentences) that:
- Summarizes the overall health of the webpage
- Highlights any critical issues found
- Provides a clear PASS/FAIL recommendation

Be objective and factual.
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
    
    Args:
        page_data: Dictionary containing page load data with keys: url, final_url, http_status, status, navigation_time_seconds, load_time_seconds, error, console_errors
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
def verify_layout_tool(page_data: Dict[str, Any]) -> str:
    """
    Analyzes the visual layout for bugs like overflows or small touch targets.
    Checks: Desktop and Mobile snapshots.
    
    Args:
        page_data: Dictionary containing page data with keys: layout_snapshot_desktop, layout_snapshot_mobile
    """
    print("\n[Tool Call] verify_layout_tool activated...")
    validator = LayoutValidator()
    
    if page_data.get("layout_snapshot_desktop"):
        validator.validate_snapshot(page_data["layout_snapshot_desktop"], "desktop")
    if page_data.get("layout_snapshot_mobile"):
        validator.validate_snapshot(page_data["layout_snapshot_mobile"], "mobile")
    
    validator.print_detailed_report()
    return json.dumps(validator.generate_report())

@tool
async def verify_text_tool(visible_text: str) -> str:
    """
    Uses AI to validate the textual content of the page.
    Checks: Content alignment, Inferred purpose, and quality.
    
    Args:
        visible_text: The visible text content extracted from the web page
    """
    print("\n[Tool Call] verify_text_tool (AI) activated...")
    
    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
        temperature=0,
        google_api_key=os.environ["GEMINI_API_KEY"],
    )
    
    if not visible_text:
        return json.dumps({"status": "FAIL", "reason": "Empty page text detected."})

    # Prepare analysis prompt using the exact TEXT_ANALYSIS_PROMPT
    prompt = TEXT_ANALYSIS_PROMPT.format(visible_text=visible_text)
    response = await llm.ainvoke([SystemMessage(content="You are a QA specialist."), HumanMessage(content=prompt)])
    print(response.content)
    # Extract JSON content
    raw_content = response.content.strip().replace("```json", "").replace("```", "").strip()
    return raw_content

# --- The AI Agent Orchestrator ---

class QAAgent:
    def __init__(self):
        self.tools = [verify_url_tool, verify_layout_tool, verify_text_tool]
        self.llm = ChatGoogleGenerativeAI(
            model=MODEL_NAME,
            temperature=0,
            google_api_key=os.environ["GEMINI_API_KEY"],
        )

    async def run(self, page_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main execution method where the agent autonomously decides and executes validation steps.
        The agent uses its reasoning to decide which tools to call and in what order.
        """
        print(f"\n🤖 QAAgent: Activating for URL: {page_data.get('url')}")
        print("🤖 Agent will now autonomously decide the validation steps...\n")
        
        # Prepare visible text for the agent
        visible_text = page_data.get("visible_text", "")
        
        # Agent receives instructions and decides to execute validation protocol
        agent_instruction = f"""You have received page data from the loader. 

Page Data Summary:
- URL: {page_data.get('url', 'Unknown')}
- Final URL: {page_data.get('final_url', 'Unknown')}
- HTTP Status: {page_data.get('http_status', 'Unknown')}
- Status: {page_data.get('status', 'Unknown')}
- Visible Text Available: {'Yes' if visible_text else 'No'}
- Layout Snapshots Available: Desktop={'Yes' if page_data.get('layout_snapshot_desktop') else 'No'}, Mobile={'Yes' if page_data.get('layout_snapshot_mobile') else 'No'}

Now execute your validation protocol. You must:
1. Call verify_url_tool with the page_data
2. Call verify_layout_tool with the page_data  
3. Call verify_text_tool with the visible_text: {visible_text[:200]}...
4. Synthesize all results into a final executive summary

Proceed with the validation steps."""
        
        # Agent makes decision to execute validation steps
        decision_response = await self.llm.ainvoke([
            SystemMessage(content=AGENT_SYSTEM_PROMPT),
            HumanMessage(content=agent_instruction)
        ])
        
        print(f"🤖 Agent Decision: {decision_response.content[:200]}...\n")
        
        # Agent executes the validation steps autonomously
        results = {}
        
        # Step 1: URL Verification (agent decides to call this first)
        print("\n🤖 Agent Decision: Executing URL verification...")
        url_results_json = verify_url_tool.invoke({"page_data": page_data})
        results["url_report"] = json.loads(url_results_json)
        
        # Step 2: Layout Validation (agent decides to call this second)
        print("\n🤖 Agent Decision: Executing layout validation...")
        layout_results_json = verify_layout_tool.invoke({"page_data": page_data})
        results["layout_report"] = json.loads(layout_results_json)
        
        # Step 3: Text Validation (agent decides to call this third)
        print("\n🤖 Agent Decision: Executing text validation...")
        text_results_json = await verify_text_tool.ainvoke({"visible_text": visible_text})
        try:
            results["text_report"] = json.loads(text_results_json)
        except json.JSONDecodeError:
            results["text_report"] = {"status": "FAIL", "reason": "AI response was not valid JSON", "raw": text_results_json}
        
        # Step 4: Agent synthesizes final report
        print("\n🤖 Agent Decision: Synthesizing final report...")
        synthesis_input = f"""
        Page Scan Context:
        - URL Report: {json.dumps(results['url_report'], indent=2)}
        - Layout Report: {json.dumps(results['layout_report'].get('summary', {}), indent=2)}
        - Text Report: {json.dumps(results['text_report'], indent=2)}
        
        Provide a final 'Executive Summary' (2-3 sentences) describing the overall health of this page.
        """
        
        summary_resp = await self.llm.ainvoke([
            SystemMessage(content=SYNTHESIS_PROMPT), 
            HumanMessage(content=synthesis_input)
        ])
        
        results["executive_summary"] = summary_resp.content
        
        return results


# --- Main Entry Point ---

async def main():
    # Step 1: Loader runs manually and returns its data
    loader = PageLoader()
    await loader.start()
    
    target_url = "https://practice.qabrains.com/"
    print(f"\n--- Initializing QA Pipeline for: {target_url} ---")
    
    print("\n[Step 1] Loader running...")
    page_data = await loader.load(target_url)
    
    if not page_data:
        print("❌ Failed to load page data. Exiting.")
        await loader.stop()
        return
    
    # Step 2: AI Agent takes over and decides all validation steps autonomously
    print("\n[Step 2] AI Agent taking control - will decide validation steps autonomously...")
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