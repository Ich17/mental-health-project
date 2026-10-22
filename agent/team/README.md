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
| Observateur | Fait le tour des équipes, repère celle qui dérive le plus | `company_overview`, `team_trends` |
| Mesure | Mesure l'effet des règles appliquées et l'enregistre en mémoire | `get_team_rules`, `measure_rule_effect`, `record_rule_effect` |
| Conseiller | Propose une règle pour l'unité prioritaire, en s'appuyant sur ce qui a marché ailleurs | `get_team_rules`, `suggest_rule` |

## Le cycle d'une règle (« s'améliore avec le temps »)

```
suggested  ── clic RH (POST /api/team/rules/{id}/apply) ──>  applied  ── 2 semaines plus tard, la Mesure ──>  measured
    └── clic RH (POST /api/team/rules/{id}/dismiss) ──> dismissed
```

En démo : Conseil Stratégie applique « pas d'ajout de réunion le jour même après 17h » depuis 4 semaines. À la première revue, la Mesure trouve +8 points de récupération et −69 % de réunions ajoutées le jour même, et le Conseiller propose la même règle à M&A, l'équipe qui dérive.

## Données : la cohorte de `data/simulate.py`

Les agents lisent la cohorte simulée de l'équipe data (M&A qui dérive, Conseil Stratégie qui a appliqué une règle il y a 4 semaines, Restructuring à 4 personnes), agrégée par `data/team_view.py`. Ils y accèdent uniquement via `contracts.py` (`company_overview`, `team_trends`, `measure_rule_effect`), qu'on pourra brancher sur des requêtes ClickHouse sans changer les signatures.

Confidentialité appliquée dans la couche data :
- une équipe de moins de 8 personnes est masquée, et pas fondue dans un total plus large (sinon on la retrouverait par différence) ;
- effectifs en tranches (« 8-12 », « 12-20 »), parts qualitatives (« majorité »), moyennes arrondies ;
- une règle ne peut viser qu'une équipe affichable.

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
| `GET /api/team/overview` | Les équipes affichables, de la plus en dérive à la plus stable |
| `GET /api/agent/runs/{id}` | Le run et ses messages, à interroger chaque seconde pour afficher la discussion |
| `GET /api/team/rules` | Toutes les règles et leur effet mesuré |
| `POST /api/team/rules/{id}/apply` / `dismiss` | La RH applique ou écarte une règle suggérée |

## Pistes pour la suite

- Planifier la revue chaque lundi matin (APScheduler dans l'API).
- Remplacer les agrégats pandas de `data/team_view.py` par les mêmes en SQL ClickHouse (`HAVING count() >= 8`).
- Pour ajouter un agent : son prompt dans `prompts/`, ses outils dans `AGENT_TOOLS`, ses types de messages dans `AGENT_KINDS` (`council.py`), sa place dans l'ordre de parole, et sa méthode dans `scripted.py`.
