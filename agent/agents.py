"""Un agent = un rôle (prompt) + ses outils + une boucle tool-use.
Classe commune : les agents individuels et les agents d'équipe l'utilisent
avec leurs propres prompts, outils et types de messages.

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
from agent.toolkit import RunContext, Tool, ToolError, run_tool

MAX_STEPS = 6


@dataclass
class Agent:
    name: str
    prompts_dir: Path                  # contient commun.md et <name>.md
    tools: dict[str, Tool]             # registre d'outils du package (individuel ou team)
    tool_names: list[str]              # outils auxquels CET agent a droit
    kinds: list[str]                   # types de messages qu'il peut poster

    @property
    def system(self) -> str:
        return (self.prompts_dir / "commun.md").read_text(encoding="utf-8") + "\n\n" + \
               (self.prompts_dir / f"{self.name}.md").read_text(encoding="utf-8")

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
        kinds = [k for k in (kinds or self.kinds) if k in self.kinds]
        tools = [self.tools[n].spec() for n in self.tool_names] + [self.post_message_spec(recipients, kinds)]
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
                    out = run_tool(ctx, self.tools, call["name"], call["input"], self.tool_names)
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
