"""Le tableau partagé sur lequel les agents se parlent.

Les agents ne s'appellent jamais directement : chacun poste un `Message`
adressé à un autre agent (ou à tous), et l'orchestrateur (council.py) donne
la parole au destinataire. Le tableau complet est sauvegardé en mémoire
pour l'écran « ce que les agents se sont dit ».
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Literal

AgentName = Literal[
    "detection", "analyse", "action",   # agent/individuel
    "observateur", "conseiller",        # agent/team
    "orchestrateur", "personne",
]

# Types de messages : ils pilotent qui parle ensuite (voir council.py).
MessageKind = Literal[
    "consigne",       # orchestrateur : lance le run
    "signal",         # Détection : ce qui a dérivé, jours à risque
    "analyse",        # Analyse : causes + mémoire (ce qui a marché)
    "question",       # n'importe quel agent : demande une précision à un autre
    "reponse",        # réponse à une question
    "proposition",    # Action : plan d'actions
    "revue",          # orchestrateur : contrôles du plan (privacy, vocabulaire)
    "message_final",  # Action : texte montré à la personne
]


@dataclass
class Message:
    author: AgentName
    to: AgentName | Literal["tous"]
    kind: MessageKind
    content: str
    data: dict = field(default_factory=dict)  # contenu structuré (actions, chiffres...)
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def render(self) -> str:
        """Version texte, telle que les autres agents la lisent."""
        head = f"[{self.author} → {self.to} | {self.kind}]"
        extra = f"\nDonnées : {self.data}" if self.data else ""
        return f"{head}\n{self.content}{extra}"


@dataclass
class Board:
    run_kind: str
    subject: str                    # user_id ou team_id
    messages: list[Message] = field(default_factory=list)

    def post(self, msg: Message) -> Message:
        self.messages.append(msg)
        return msg

    def last(self, kind: MessageKind | None = None, author: AgentName | None = None) -> Message | None:
        for m in reversed(self.messages):
            if (kind is None or m.kind == kind) and (author is None or m.author == author):
                return m
        return None

    def transcript(self) -> str:
        return "\n\n".join(m.render() for m in self.messages)

    def to_dict(self) -> dict:
        return {"run_kind": self.run_kind, "subject": self.subject,
                "messages": [asdict(m) for m in self.messages]}
