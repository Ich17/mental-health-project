# Mental Health Project

Agent anti-épuisement (Hackathon Accel × Aiven). Brief complet : [CLAUDE.md](CLAUDE.md).

## Le projet en 3 blocs

1. **La data** : on récupère les métadonnées d'agenda (jamais le contenu) et les données de récupération Whoop (sommeil, HRV, score).
2. **Les agents** : Claude lit ces données, trouve ce qui fatigue la personne, prévoit la semaine et propose de bloquer des créneaux.
3. **Aiven** : héberge l'app (Runtime) et les bases (Postgres pour la mémoire, ClickHouse pour les séries, Valkey pour le flux).

## Qui bosse où (proposition, à ajuster)

| Rôle | Dossier | Mission |
|---|---|---|
| Data agenda | `data/` | Connecteur Google Calendar → métadonnées des réunions |
| Data Whoop | `data/` | Connecteur Whoop → récupération, sommeil, HRV |
| Agents | `agent/` | Boucle Claude, outils, mémoire Postgres |
| Aiven + API | `api/` | Déploiement Aiven Runtime, branchement des bases, routes |
| Front | `web/` | Les écrans de la démo |

**`contracts.py`** est le pont entre data et agents : il renvoie des données fictives pour l'instant, donc tout le monde peut avancer en parallèle. Les deux personnes data le remplissent avec les vraies données sans changer les noms des fonctions.

Les fichiers à la racine (`Dockerfile`, `CLAUDE.md`) et ceux qui commencent par un point servent à la config : pas besoin d'y toucher.

## Démarrer

```bash
git clone https://github.com/Ich17/mental-health-project
cd mental-health-project
python3.12 -m venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\activate
pip install -r api/requirements.txt
cp .env.example .env                    # puis remplir avec vos accès
uvicorn api.main:app --reload           # API sur http://localhost:8000 (/health, /docs)
cd web && npm install && npm run dev    # front sur http://localhost:5173
```

**Seule règle fixe** : pas de secrets ni de données perso dans git (`.env` et `data/raw/` sont ignorés).
