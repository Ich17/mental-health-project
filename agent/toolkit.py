"""Briques communes aux agents individuels et aux agents d'équipe :
outil, contexte d'un run, exécution d'un outil avec contrôle des droits."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class RunContext:
    store: Any                          # agent.memory.InMemoryMemory ou PostgresMemory
    user_id: str | None = None          # run individuel : la personne
    team_id: str | None = None          # run équipe : l'équipe (jamais un individu)
    draft_actions: list[dict] = field(default_factory=list)
    hypotheses_saved: int = 0


class ToolError(Exception):
    """Erreur renvoyée à l'agent (il peut corriger son appel)."""


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    fn: Callable[..., Any]

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.schema}


def obj(props: dict | None = None, required: list[str] | None = None) -> dict:
    """Schéma JSON d'un objet, pour les paramètres d'un outil."""
    return {"type": "object", "properties": props or {}, "required": required or []}


def run_tool(ctx: RunContext, tools: dict[str, Tool], name: str, args: dict, allowed: list[str]):
    if name not in allowed:
        raise ToolError(f"outil « {name} » non autorisé pour cet agent")
    try:
        return tools[name].fn(ctx, **args)
    except TypeError as e:
        raise ToolError(f"arguments invalides : {e}") from e
