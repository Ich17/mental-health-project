# agent/ : trois agents qui délibèrent

Détection, Analyse et Action se parlent sur un tableau partagé avant de proposer quoi que ce soit à la personne. Chaque agent est un vrai agent Claude (boucle tool use du SDK Anthropic), avec son propre prompt et **ses propres outils**. Ce n'est pas un seul appel LLM.

```
Détection --signal--> Analyse --analyse--> Action --proposition--> revue (code)
     ^                  |  ^                 |                         |
     +----question------+  +----question-----+   <--- à corriger ------+
                                                     validé -> message_final
```

| Agent | Rôle | Outils |
|---|---|---|
| Détection | Dérives vs la base perso, jours rouges à venir | `get_daily_metrics`, `forecast_week` |
| Analyse | Causes + mémoire (ce qui a déjà marché) | `get_drivers`, `get_memory`, `evaluate_experiment`, `save_hypothesis` |
| Action | Plan : blocs d'agenda, expérience, brouillon de message | `get_free_slots`, `propose_block`, `start_experiment`, `draft_message` |

## Lancer

```bash
python -m agent.cli --scripted               # sans clé API (cerveau de démo déterministe)
python -m agent.cli                          # avec Claude si ANTHROPIC_API_KEY est défini
python -m agent.cli --kind chat --question "Pourquoi je suis à plat le lundi ?"
python -m agent.cli --trace                  # affiche aussi les appels d'outils
python -m pytest -q agent/tests
```

Sans `DATABASE_URL`, la mémoire est en mémoire vive. Avec, tout va dans Postgres (`postgres.sql`).

## Fichiers

| Fichier | Rôle |
|---|---|
| `council.py` | L'orchestrateur : qui parle, quand, et la revue du plan |
| `agents.py` | Un agent = prompt + outils + boucle tool use, terminée par `post_message` |
| `tools.py` | Les outils et les droits de chaque agent (`AGENT_TOOLS`) |
| `guardrails.py` | Contrôles déterministes de la section 3 du CLAUDE.md |
| `board.py` | Messages et tableau partagé |
| `memory.py` | Mémoire Postgres, ou en mémoire vive sans `DATABASE_URL` |
| `llm.py` | Client Claude ; `AGENT_MODE` = auto, live ou scripted |
| `scripted.py` | Cerveau de démo : mêmes outils, mêmes données, pas d'appel LLM |
| `prompts/` | Un prompt par agent, plus `commun.md` |

## Ce qui est garanti par le code (pas par les prompts)

- Un agent n'a que ses outils. Le `user_id` vient du contexte du run, jamais d'un argument du LLM.
- Aucun agent n'écrit dans l'agenda. Les outils d'action remplissent un brouillon ; l'orchestrateur le relit et l'enregistre en `proposed` ; seule la route `POST /api/actions/{id}/accept` l'exécute, après le clic.
- Titre « Occupé » et visibilité privée imposés dans `propose_block` et dans `contracts.create_calendar_block`.
- Revue du plan : vocabulaire interdit (stress, humeur, émotion, diagnostic…), blocs conformes, orientation obligatoire si 3 jours rouges ou plus. 2 révisions maximum, puis les actions non conformes sont écartées. Un message final non conforme est remplacé par un texte sûr écrit par le code.
- Une question maximum par agent et par run, 12 tours maximum.

## Routes API (`api/agent_routes.py`)

| Route | Effet |
|---|---|
| `POST /api/agent/runs` `{"kind": "semaine" \| "jour" \| "chat", "question": ...}` | Lance un run en arrière-plan, renvoie `run_id` |
| `GET /api/agent/runs/{id}` | Le run et tous ses messages : à interroger chaque seconde pour afficher la discussion en direct |
| `GET /api/agent/runs` | Historique des runs |
| `GET /api/actions?status=proposed` | Actions en attente du clic |
| `POST /api/actions/{id}/accept` / `reject` | Exécute ou refuse une action |

## Prochaines étapes

- Tester en mode live avec une vraie clé, et ajuster les prompts.
- Brancher le planificateur (dimanche 19h : `semaine`, chaque matin : `jour`) dans l'API.
- Agent RH : même mécanique, outils `team_trends` (agrégats n ≥ 8) ; `guardrails.check_hr_text` est déjà prêt.
