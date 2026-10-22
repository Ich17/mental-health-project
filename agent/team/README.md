# agent/team : les agents côté entreprise

Règle d'or : l'entreprise est alertée sur des **causes**, jamais sur des **personnes**.

## Le déroulé d'une revue d'entreprise

```
Observateur --signal--> Mesure --mesure--> Conseiller --proposition--> revue (code) --> message_final RH
     ^                    ^                    |
     +----question--------+------question------+
```

| Agent | Rôle | Outils |
|---|---|---|
| Observateur | Fait le tour des unités, repère celle qui dérive le plus | `company_overview`, `team_trends` |
| Mesure | Mesure l'effet des règles appliquées et l'enregistre en mémoire | `get_team_rules`, `measure_rule_effect`, `record_rule_effect` |
| Conseiller | Propose une règle pour l'unité prioritaire, en s'appuyant sur ce qui a marché ailleurs | `get_team_rules`, `suggest_rule` |

## Le cycle d'une règle (« s'améliore avec le temps »)

```
suggested  ── clic RH (POST /api/team/rules/{id}/apply) ──>  applied  ── 2 semaines plus tard, la Mesure ──>  measured
    └── clic RH (POST /api/team/rules/{id}/dismiss) ──> dismissed
```

En démo : une règle a été appliquée il y a 4 semaines chez Coverage. À la première revue, la Mesure trouve +4 points de récupération et −50 % de réunions ajoutées le jour même, et le Conseiller s'en sert pour proposer une règle comparable à M&A, l'unité qui dérive.

## Données : la cohorte simulée (`data/cohort.py`)

40 salariés, 4 équipes, 8 semaines : M&A dérive, Leveraged Finance est stable, Coverage s'améliore après sa règle, Data compte moins de 8 personnes. On y accède uniquement via `contracts.py` (`company_overview`, `team_trends`, `measure_rule_effect`), qu'on branchera sur ClickHouse sans changer les signatures.

Confidentialité appliquée dans la couche data :
- une équipe de moins de 8 personnes n'est jamais affichée seule ; son département est présenté **en bloc, sans ses équipes sœurs**, sinon on pourrait déduire la petite équipe par différence ;
- effectifs en tranches (« 10-15 »), parts qualitatives (« majorité »), moyennes arrondies ;
- une règle ne peut viser qu'une unité affichable.

Et dans la revue du code : jamais d'effectif < 8 ni d'identifiant dans un texte RH, pas de vocabulaire interdit ; pas de doublon si la même règle est déjà suggérée ou appliquée.

## Lancer

```bash
python -m agent.team.cli --scripted
python -m pytest -q agent/team
```

## Routes API

| Route | Effet |
|---|---|
| `POST /api/agent/team-runs` `{"wait": false}` | Lance une revue d'entreprise, renvoie `run_id` (suivi via `GET /api/agent/runs/{id}`) |
| `GET /api/team/overview` | Les unités affichables, de la plus en dérive à la plus stable |
| `GET /api/team/rules` | Toutes les règles et leur effet mesuré |
| `POST /api/team/rules/{id}/apply` / `dismiss` | La RH applique ou écarte une règle suggérée |

## Pistes pour la suite

- Planifier la revue chaque lundi matin (APScheduler dans l'API).
- Brancher `data/cohort.py` sur ClickHouse quand la cohorte y est chargée.
- Pour ajouter un agent : son prompt dans `prompts/`, ses outils dans `AGENT_TOOLS`, ses types de messages dans `AGENT_KINDS` (`council.py`), sa place dans l'ordre de parole, et sa méthode dans `scripted.py`.
