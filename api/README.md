# api/ : le serveur et Aiven

- `main.py` : FastAPI (`/health`, routes `/api/*`), sert aussi le front buildé.
- `db.py` : connexion Postgres via `DATABASE_URL` (injectée par Aiven).
- `requirements.txt` : dépendances Python.
- `docker-compose.yml` : optionnel, bases locales pour coder sans Aiven.
- `tests/` : `python -m pytest -q api/tests`.

Déployer : Console Aiven → Overview → Actions → « Deploy latest commit » (un push ne redéploie pas).
