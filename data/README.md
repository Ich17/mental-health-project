# data/ : récupérer les vraies données

- `gcal.py` (à créer) : Google Calendar → début, fin, nb d'invités, interne/externe, date de création. Jamais le titre ni la description.
- `whoop.py` (à créer) : Whoop → récupération, HRV, FC repos, sommeil, strain.
- `clickhouse.sql` : les tables où ranger ces données.
- `raw/` : exports JSON de secours (ignoré par git).

Ensuite, remplir `contracts.py` (à la racine) avec les vraies données. Voir CLAUDE.md §4, §7, §8.
