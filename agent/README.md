# agent/ : les agents qui délibèrent

```
agent/
├── team/              agents de l'entreprise : Observateur, Mesure, Conseiller (voir team/README.md)
│
├── agents.py          classe Agent : prompt + outils + boucle tool use (SDK Anthropic)
├── board.py           tableau partagé : les messages que les agents s'échangent
├── toolkit.py         Tool, RunContext, contrôle des droits sur les outils
├── guardrails.py      contrôles déterministes (CLAUDE.md §3)
├── memory.py          mémoire Postgres (DATABASE_URL), ou en mémoire vive sans base
├── llm.py             client Claude ; AGENT_MODE = auto | live | scripted
├── scripted_utils.py  briques des cerveaux de démo (sans appel LLM)
└── postgres.sql       schéma de la mémoire
```

Les agents ne s'appellent pas directement : chacun poste un message (`to`, `kind`, `content`, `data`) sur le tableau partagé, et l'orchestrateur (`council.py`) donne la parole au destinataire. Un agent peut poser une `question` à un autre, qui répond, puis la parole revient. Chaque tour est une vraie boucle tool use, terminée obligatoirement par l'outil `post_message`.

```bash
python -m agent.team.cli --scripted          # sans clé API
python -m agent.team.cli                     # avec Claude si ANTHROPIC_API_KEY est défini
python -m pytest -q agent
```
