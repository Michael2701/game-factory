"""Test doubles shared by node tests."""

from langchain_core.messages import AIMessage


class FakeLLM:
    """Returns scripted replies in order and records the prompts it received.

    A reply that is an Exception instance is raised instead of returned.
    """

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts: list[str] = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return AIMessage(content=reply)
