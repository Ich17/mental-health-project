"""Accès au LLM, derrière une interface minuscule.

Deux implémentations :
- `ClaudeLLM`  : le vrai Claude via le SDK Anthropic (tool use).
- `ScriptedLLM` (dans scripted.py) : un « cerveau de démo » déterministe qui
  appelle les mêmes outils et poste des messages construits à partir de leurs
  résultats. Sert aux tests, à la CI et au plan B si la clé API ou le réseau
  lâchent pendant la démo.

Les messages suivent le format de l'API Anthropic (listes de blocs en dict).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Reply:
    stop_reason: str                              # "tool_use" | "end_turn" | ...
    blocks: list[dict] = field(default_factory=list)

    @property
    def tool_calls(self) -> list[dict]:
        return [b for b in self.blocks if b["type"] == "tool_use"]

    @property
    def text(self) -> str:
        return "\n".join(b["text"] for b in self.blocks if b["type"] == "text").strip()


class LLM(Protocol):
    def complete(self, *, agent: str, system: str, messages: list[dict],
                 tools: list[dict], tool_choice: dict | None = None) -> Reply: ...


class ClaudeLLM:
    def __init__(self, model: str | None = None, max_tokens: int = 1500):
        import anthropic  # import paresseux : la CI tourne sans clé

        self.client = anthropic.Anthropic()
        self.model = model or os.getenv("LLM_MODEL", "claude-sonnet-5-5")
        self.max_tokens = max_tokens

    def complete(self, *, agent, system, messages, tools, tool_choice=None) -> Reply:
        kwargs = {"tool_choice": tool_choice} if tool_choice else {}
        resp = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, system=system,
            messages=messages, tools=tools, **kwargs,
        )
        blocks = []
        for b in resp.content:
            if b.type == "text":
                blocks.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                blocks.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
        return Reply(stop_reason=resp.stop_reason, blocks=blocks)


def default_llm() -> LLM:
    """Claude si une clé est configurée et AGENT_MODE != scripted, sinon le script."""
    mode = os.getenv("AGENT_MODE", "auto")
    if mode == "live" or (mode == "auto" and os.getenv("ANTHROPIC_API_KEY")):
        return ClaudeLLM()
    from agent.scripted import ScriptedLLM

    return ScriptedLLM()
