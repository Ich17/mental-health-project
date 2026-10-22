# Mental Health Project

Agent anti-épuisement (Hackathon Accel × Aiven). Le brief du projet est dans [CLAUDE.md](CLAUDE.md). Il évoluera, tout comme ce README.

## Démarrer

```bash
git clone https://github.com/Ich17/mental-health-project
cd mental-health-project
python3.12 -m venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\activate
cp .env.example .env    # puis remplir avec vos accès
```

## Le seul point fixe

Pas de secrets ni de données perso dans git : les clés vont dans `.env`, les exports bruts dans `data/raw/` (tous deux ignorés).

Le reste (organisation, branches, répartition) se décide en équipe au fil du projet.

## Lancer le squelette

Point de départ pour avancer vite, à modifier librement.

```bash
pip install -r requirements.txt
uvicorn api.main:app --reload          # API sur http://localhost:8000 (/health, /docs)
cd web && npm install && npm run dev   # front sur http://localhost:5173
python -m pytest -q                    # tests
```

Optionnel, bases locales sans Aiven : `docker compose up -d postgres clickhouse valkey`, puis mettre les URL locales dans `.env` (voir `docker-compose.yml`).

| Dossier | Contenu actuel |
|---|---|
| `contracts.py` | Fonctions data ↔ agent, renvoient des mocks pour l'instant |
| `api/` | FastAPI : `/health`, routes `/api/*` branchées sur `contracts.py`, sert le front buildé |
| `agent/` | Vide, pour la boucle agent |
| `data/` | Schémas SQL (`sql/`), connecteurs à venir |
| `web/` | React + Vite + Tailwind, une page de test |

Déploiement Aiven Runtime : le `Dockerfile` construit le front et lance l'API sur le port 8000. Un push ne redéploie pas, il faut cliquer « Deploy latest commit » dans la console.
