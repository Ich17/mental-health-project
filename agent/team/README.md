# agent/team : les agents côté entreprise

Règle d'or : l'entreprise est alertée sur des **causes**, jamais sur des **personnes**. Les agents d'équipe ne voient que des agrégats (n ≥ 8, filtré dans la requête SQL de `contracts.team_trends`).

## Ce qui existe déjà (V1 qui tourne)

```
Observateur --signal--> Conseiller --proposition--> revue (code) --> message_final pour la RH
     ^                     |
     +------question-------+
```

| Agent | Rôle | Outils |
|---|---|---|
| Observateur | Lit les tendances anonymes de l'équipe | `team_trends` |
| Conseiller | Propose une règle d'équipe, en s'appuyant sur l'effet des règles passées | `get_team_rules`, `suggest_rule` |

```bash
python -m agent.team.cli --team ma --scripted
python -m pytest -q agent/team
```

## Fichiers

| Fichier | Rôle |
|---|---|
| `council.py` | L'orchestrateur : ordre de parole, revue `guardrails.check_hr_text`, enregistrement de la règle |
| `tools.py` | Outils et droits (`AGENT_TOOLS`) |
| `prompts/` | `commun.md` + un fichier par agent |
| `scripted.py` | Cerveau de démo sans clé API (utilisé par les tests et la CI) |

## Pistes pour la suite

- Un agent **Mesure** qui évalue l'effet d'une règle appliquée (récupération moyenne 4 semaines avant / après) : c'est l'écran 4 et la boucle « s'améliore avec le temps ».
- Remonter au département quand l'équipe est trop petite, au lieu de s'arrêter.
- Pour ajouter un agent : son prompt dans `prompts/`, ses outils dans `AGENT_TOOLS`, ses types de messages dans `AGENT_KINDS` (council.py), sa place dans l'ordre de parole, et sa méthode dans `scripted.py`.

Tant que tu restes dans `agent/team/`, tu ne touches à rien du côté individuel. Les fichiers communs (`agent/*.py`, `postgres.sql`) : prévenir avant de les modifier.
