from typing import TypedDict

from langgraph.graph import StateGraph, START, END
from langchain_ollama import ChatOllama


class State(TypedDict):
    idea: str
    spec: str
    result: str


llm = ChatOllama(
    model="qwen2.5-coder:14b",
    temperature=0.2,
)


def planner_node(state: State) -> State:
    prompt = f"""
You are a game designer.
Create a short technical spec for a tiny Phaser browser game.

Game idea:
{state["idea"]}

Return:
- title
- core mechanic
- scenes
- controls
- win/lose condition
- minimal Playwright tests
"""
    response = llm.invoke(prompt)
    return {
        **state,
        "spec": response.content,
    }


def reviewer_node(state: State) -> State:
    prompt = f"""
Review this game spec.
Say if it is small enough for a first MVP.
If not, simplify it.

Spec:
{state["spec"]}
"""
    response = llm.invoke(prompt)
    return {
        **state,
        "result": response.content,
    }


graph = StateGraph(State)

graph.add_node("planner", planner_node)
graph.add_node("reviewer", reviewer_node)

graph.add_edge(START, "planner")
graph.add_edge("planner", "reviewer")
graph.add_edge("reviewer", END)

app = graph.compile()

final_state = app.invoke({
    "idea": "A simple game where the player dodges falling blocks for 60 seconds.",
    "spec": "",
    "result": "",
})

print("\n=== SPEC ===\n")
print(final_state["spec"])

print("\n=== REVIEW ===\n")
print(final_state["result"])
