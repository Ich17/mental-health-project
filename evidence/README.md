# Preuve avant / après

Isolé du reste du projet (ne modifie ni `api/`, ni `agent/`, ni `data/`).

```
python -m evidence.before_after          # lit data/raw/team_daily.json (fichier créé par python -m data.simulate_daily)
python -m evidence.before_after --demo   # sans données perso
```

Écrit `evidence/out/rapport.html` (à ouvrir dans le navigateur) et `evidence/out/rapport.json`.

- Partie 1 : backtest. Chaque matin, le modèle ne voit que le passé et estime le risque d'une récupération rouge (< 34) le lendemain.
- Partie 2 : projection. Sur les jours signalés, l'agent déplace jusqu'à 2 h de réunions ; gain = pente perso mesurée en partie 1 × heures × part causale (25 / 50 / 100 %), 60 % des propositions acceptées.
