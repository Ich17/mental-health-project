# agent/ : les agents qui délibèrent

Deux familles d'agents, une mécanique commune.

```
agent/
├── individuel/     agents du salarié : Détection, Analyse, Action      → Ichane
├── team/           agents de l'entreprise : Observateur, Conseiller    → Thomas
│
├── agents.py       classe Agent : prompt + outils + boucle tool use     ┐
├── board.py        tableau partagé (messages entre agents)              │
├── toolkit.py      Tool, RunContext, contrôle des droits sur les outils │  commun :
├── guardrails.py   contrôles déterministes (CLAUDE.md §3)               │  à modifier
├── memory.py       mémoire Postgres, ou en mémoire vive sans DB         │  à deux
├── llm.py          client Claude ; AGENT_MODE = auto | live | scripted  │
├── postgres.sql    schéma de la mémoire                                 ┘
└── tests/          tests du code commun
```

Chaque dossier (`individuel/`, `team/`) a la même forme : `council.py` (l'orchestrateur), `tools.py` (outils et droits de chaque agent), `prompts/` (un fichier par agent + `commun.md`), `scripted.py` (cerveau de démo sans clé API), `cli.py`, `tests/`. On peut donc travailler en parallèle sans se marcher dessus : seuls les fichiers communs demandent de se prévenir.

## Lancer

```bash
python -m agent.individuel.cli --scripted        # sans clé API
python -m agent.individuel.cli --trace           # avec Claude si ANTHROPIC_API_KEY est défini
python -m agent.individuel.cli --kind chat --question "Pourquoi je suis à plat le lundi ?"
python -m agent.team.cli --team ma --scripted
python -m pytest -q api/tests agent
```

Sans `DATABASE_URL`, la mémoire est en mémoire vive. Avec, tout va dans Postgres.

## Le principe

Les agents ne s'appellent pas directement : chacun poste un message (`to`, `kind`, `content`, `data`) sur le tableau partagé, et l'orchestrateur donne la parole au destinataire. Un agent peut poser une `question` à un autre, qui répond, puis la parole revient. Chaque tour d'agent est une vraie boucle tool use, terminée obligatoirement par l'outil `post_message`.

## Ce qui est garanti par le code (pas par les prompts)

- Un agent n'a que ses outils (`AGENT_TOOLS` dans chaque `tools.py`). Le `user_id` ou le `team_id` vient du contexte du run, jamais d'un argument du LLM.
- Aucun agent n'écrit dans l'agenda. Les outils d'action remplissent un brouillon, l'orchestrateur le relit, puis l'enregistre en `proposed`. Seule la route `POST /api/actions/{id}/accept` l'exécute, après le clic.
- Titre « Occupé » et visibilité privée imposés dans `propose_block` et `contracts.create_calendar_block`.
- Revue par le code : vocabulaire interdit (stress, humeur, émotion, diagnostic…), orientation obligatoire si 3 jours rouges ou plus, jamais d'effectif < 8 ni d'identifiant côté équipe. Un texte final non conforme est remplacé par un texte sûr.
- Une équipe trop petite (`insufficient_group`) ne déclenche même pas les agents d'équipe.

## Routes API (`api/agent_routes.py`)

| Route | Effet |
|---|---|
| `POST /api/agent/runs` `{"kind": "semaine" \| "jour" \| "chat", "question": ...}` | Lance un run individuel en arrière-plan, renvoie `run_id` |
| `GET /api/agent/runs/{id}` | Le run et ses messages : à interroger chaque seconde pour afficher la discussion en direct |
| `GET /api/agent/runs` | Historique des runs |
| `GET /api/actions?status=proposed` | Actions en attente du clic |
| `POST /api/actions/{id}/accept` / `reject` | Exécute ou refuse une action |
| `POST /api/agent/team-runs/{team_id}` | Délibération des agents d'équipe |
