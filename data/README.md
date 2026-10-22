# data/ : récupérer les vraies données

## Données de travail (métadonnées uniquement)

Trois sources, **un seul format** (`WorkEvent` dans `events.py`, = table ClickHouse `work_events`) :

| user_id (hash) | team_id | ts | end_ts | kind | created_ts | n_attendees | is_external | status | source | duration_min | is_after_hours | is_weekend |
|---|---|---|---|---|---|---|---|---|---|---|---|---|

- `gcal.py` : Google Calendar → réunions (heures, invités, interne/externe, date de création). Jamais le titre.
- `gmail.py` : Gmail (scope `gmail.metadata`) → mails envoyés/reçus (heure, nb de destinataires). Jamais le sujet ni le corps.
- `simulate_work.py` : **mode mock**, 10 personnes × 13 semaines dont 3 dérives progressives et 1 rush ponctuel.
  La vérité terrain (`*_truth.json`) permet de mesurer la détection (jours d'avance, fausses alertes).
- `viva.py` : échantillon de démo **Microsoft Viva Insights** (Outlook + Teams), 300 personnes × 35 semaines,
  7 équipes, format hebdomadaire (table `work_weekly`). Données de démo Microsoft (licence MIT).

```bash
python -m data.ingest mock                 # synthétique (aucun compte requis)
python -m data.ingest viva                 # échantillon Microsoft Viva
python -m data.ingest google --days 90     # vrai compte → voir GOOGLE_SETUP.md
python -m data.ingest mock --clickhouse    # + insertion ClickHouse (CLICKHOUSE_URL)
```
Dans le code : `from data.ingest import load_events` (lit `DATA_MODE=mock|google`).

Tous les fichiers produits vont dans `raw/` (ignoré par git).

## Autres
- `whoop.py` (à créer) : Whoop → récupération, HRV, FC repos, sommeil, strain.
- `clickhouse.sql` : les tables où ranger ces données.

Ensuite, remplir `contracts.py` (à la racine) avec les vraies données. Voir CLAUDE.md §4, §7, §8.
