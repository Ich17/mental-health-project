"""Un agent = un rôle (prompt) + ses outils + une boucle tool-use.

Chaque tour d'un agent :
1. il lit le tableau (toute la discussion jusqu'ici) et la consigne de l'orchestrateur ;
2. il appelle ses outils autant que nécessaire (6 étapes max) ;
3. il termine obligatoirement par `post_message`, qui devient un `Message` du tableau.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from agent.board import Board, Message
from agent.llm import LLM
from agent.tools import AGENT_TOOLS, TOOLS, RunContext, ToolError, run_tool

PROMPTS = Path(__file__).with_name("prompts")
MAX_STEPS = 6

# Types de messages que chaque agent a le droit de poster.
AGENT_KINDS: dict[str, list[str]] = {
    "detection": ["signal", "reponse"],
    "analyse": ["analyse", "question", "reponse"],
    "action": ["proposition", "message_final", "question"],
}


@dataclass
class Agent:
    name: str

    @property
    def system(self) -> str:
        return (PROMPTS / "commun.md").read_text(encoding="utf-8") + "\n\n" + \
               (PROMPTS / f"{self.name}.md").read_text(encoding="utf-8")

    @property
    def tool_names(self) -> list[str]:
        return AGENT_TOOLS[self.name]

    def post_message_spec(self, recipients: list[str], kinds: list[str]) -> dict:
        return {
            "name": "post_message",
            "description": "Poste ton message sur le tableau partagé. Termine ton tour.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "enum": [r for r in recipients if r != self.name] + ["tous"]},
                    "kind": {"type": "string", "enum": kinds},
                    "content": {"type": "string", "description": "le message, en français"},
                    "data": {"type": "object", "description": "contenu structuré facultatif"},
                },
                "required": ["to", "kind", "content"],
            },
        }

    def take_turn(self, llm: LLM, board: Board, ctx: RunContext, instruction: str,
                  recipients: list[str], kinds: list[str] | None = None,
                  trace: list[dict] | None = None) -> Message:
        """`kinds` restreint les types de message autorisés à ce tour
        (ex. seulement `reponse` quand l'agent doit répondre à une question)."""
        kinds = [k for k in (kinds or AGENT_KINDS[self.name]) if k in AGENT_KINDS[self.name]]
        tools = [TOOLS[n].spec() for n in self.tool_names] + [self.post_message_spec(recipients, kinds)]
        messages: list[dict] = [{"role": "user", "content": (
            f"## Tableau partagé\n\n{board.transcript() or '(vide)'}\n\n"
            f"## Consigne de l'orchestrateur\n\n{instruction}")}]

        for step in range(MAX_STEPS):
            last = step == MAX_STEPS - 1
            choice = {"type": "tool", "name": "post_message"} if last else {"type": "any"}
            reply = llm.complete(agent=self.name, system=self.system, messages=messages,
                                 tools=tools, tool_choice=choice)
            messages.append({"role": "assistant", "content": reply.blocks})

            results, posted = [], None
            for call in reply.tool_calls:
                if call["name"] == "post_message":
                    try:
                        posted = self._to_message(call["input"], recipients, kinds)
                        results.append(_result(call, {"ok": True}))
                    except ToolError as e:
                        results.append(_result(call, str(e), error=True))
                    continue
                try:
                    out = run_tool(ctx, call["name"], call["input"], self.tool_names)
                    results.append(_result(call, out))
                except ToolError as e:
                    out = str(e)
                    results.append(_result(call, out, error=True))
                if trace is not None:
                    trace.append({"agent": self.name, "tool": call["name"],
                                  "input": call["input"], "output": out})
            if posted:
                return posted
            messages.append({"role": "user", "content": results or
                             "Termine ton tour avec post_message."})

        raise RuntimeError(f"{self.name} n'a pas posté de message en {MAX_STEPS} étapes")

    def _to_message(self, args: dict, recipients: list[str], kinds: list[str]) -> Message:
        to, kind = args.get("to"), args.get("kind")
        if kind not in kinds:
            raise ToolError(f"type « {kind} » interdit à ce tour. Autorisés : {kinds}")
        if to not in recipients + ["tous"] or to == self.name:
            raise ToolError(f"destinataire « {to} » inconnu dans ce run")
        data = args.get("data") or {}
        return Message(author=self.name, to=to, kind=kind,
                       content=str(args.get("content", "")).strip(), data=data)


def _result(call: dict, out, error: bool = False) -> dict:
    content = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, default=str)
    block = {"type": "tool_result", "tool_use_id": call["id"], "content": content}
    if error:
        block["is_error"] = True
    return block
