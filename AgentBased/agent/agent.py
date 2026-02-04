from langchain_community.llms import Ollama
from langchain.agents import initialize_agent, AgentType
from langchain.tools import Tool
from langchain.memory import ConversationBufferMemory
import subprocess

# -------- LLM --------
llm = Ollama(model="qwen3:4b", temperature=0.2)

# -------- TOOLS --------
def shell(cmd: str) -> str:
    try:
        out = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=5
        )
        return out.stdout or out.stderr or "done"
    except Exception as e:
        return str(e)

tools = [
    Tool(
        name="Shell",
        func=shell,
        description="Run Linux shell commands"
    )
]

# -------- MEMORY --------
memory = ConversationBufferMemory(
    memory_key="chat_history",
    return_messages=True
)

# -------- AGENT --------
agent = initialize_agent(
    tools=tools,
    llm=llm,
    agent=AgentType.CHAT_CONVERSATIONAL_REACT_DESCRIPTION,
    memory=memory,
    verbose=True
)

# -------- LOOP --------
print("Agent ready. type exit")

while True:
    q = input(">>> ")
    if q.lower() in {"exit", "quit"}:
        break
    print(agent.run(q))
