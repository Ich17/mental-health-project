# Mental Health Project

Agent anti-épuisement (Hackathon Accel × Aiven). Le brief complet est dans [CLAUDE.md](CLAUDE.md) : à lire avant de coder.

## Installation (5 min)

Prérequis : Python 3.12, Git, (Node 20 pour le front).

```bash
git clone https://github.com/Ich17/mental-health-project
cd mental-health-project
python3.12 -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -r requirements.txt    # dès que le squelette est mergé
cp .env.example .env               # puis remplir avec les accès Aiven / clés
```

Avec `uv` (plus rapide) : `uv venv && source .venv/bin/activate && uv pip install -r requirements.txt`.

## Règles d'équipe

1. **Jamais de push sur `main`.** Une branche par tâche (`data/whoop`, `agent/loop`, `web/dashboard`…), puis une PR. Une relecture rapide par quelqu'un d'autre, puis merge.
2. **Petites PR, souvent.** On merge plusieurs fois par heure, pas une grosse PR à 15h.
3. **Jamais de secrets ni de données perso dans git.** Les clés vont dans `.env` (ignoré). Les exports Whoop / agenda vont dans `data/raw/` (ignoré).
4. **`.env.example` à jour** dès qu'on ajoute une variable d'environnement.
5. **Ne pas changer les signatures de `contracts.py`** sans prévenir les deux côtés (data ↔ agent).
6. **Privacy (CLAUDE.md §3) dans le code, pas seulement dans les prompts** : pas de contenu de mail/réunion, jamais d'émotions, seuil n ≥ 8 dans le SQL, événements « Occupé » en privé, l'agent propose avant d'agir.
7. **Déploiement Aiven Runtime** : un push ne redéploie pas. Après merge sur `main` : Console → Overview → Actions → « Deploy latest commit ».
