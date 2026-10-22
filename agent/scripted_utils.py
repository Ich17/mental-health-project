"""Outils partagés par les cerveaux de démo (ScriptedLLM) : construire des appels
d'outils et des messages, relire les résultats et le tableau. Pas d'appel LLM."""
from __future__ import annotations

import ast
import itertools
import json
import re

from agent.llm import Reply

_ids = itertools.count(1)


def _call(name: str, **args) -> dict:
    return {"type": "tool_use", "id": f"s{next(_ids)}", "name": name, "input": args}


def _post(to: str, kind: str, content: str, data: dict | None = None) -> Reply:
    args = {"to": to, "kind": kind, "content": content}
    if data:
        args["data"] = data
    return Reply("tool_use", [_call("post_message", **args)])


def _board_data(board: str, kind: str) -> dict:
    """Récupère le champ `data` du dernier message d'un type donné sur le tableau."""
    blocks = [b for b in board.split("\n\n[") if f"| {kind}]" in b.split("\n")[0]]
    if not blocks:
        return {}
    m = re.search(r"Données : (\{.*\})", blocks[-1], re.S)
    return ast.literal_eval(m.group(1)) if m else {}


def _results(messages: list[dict]) -> dict[str, object]:
    """Résultats des outils déjà appelés à ce tour, indexés par nom d'outil."""
    names, out = {}, {}
    for m in messages:
        if m["role"] == "assistant":
            for b in m["content"]:
                if b["type"] == "tool_use":
                    names[b["id"]] = b["name"]
        elif isinstance(m["content"], list):
            for b in m["content"]:
                if b.get("type") == "tool_result" and not b.get("is_error"):
                    try:
                        out.setdefault(names[b["tool_use_id"]], []).append(json.loads(b["content"]))
                    except (json.JSONDecodeError, KeyError):
                        pass
    return out
