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
