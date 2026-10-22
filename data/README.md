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
- `clickhouse.sql` : les tables où ranger ces données.

## Données de récupération (WHOOP) et cohorte simulée

- `whoop.py` : Whoop → récupération, HRV, FC repos, sommeil, strain (une ligne par jour, format `recovery_daily`).
- `check_whoop.py` : bilan qualité + nettoyage → `whoop_daily_clean.json` / `.csv` (Excel FR). Jours manquants, strain < 1 (montre pas portée), HRV sur nuit < 3 h et valeurs impossibles sont estimés par la moyenne des jours voisins ; la colonne `imputed` liste les champs estimés. Sans pandas.
- Alignement : la ligne du jour D = récupération / HRV / sommeil de la nuit D-1 → D, et strain de la journée D. Pour les analyses, la charge du jour D s'apparie avec la récupération de D+1.
- `simulate.py` : ~50 profils fictifs (agenda, mails, présence, récupération) pour la vue RH et le profil de secours `persona_demo`. Même format `work_events` que `events.py` (+ `kind=presence_green` pour le temps « vert » Teams) ; ses équipes (`ma`, `pe`, `conseil`, `levfin`, `restru`) ne touchent pas au mode mock.
- `raw/` : exports JSON de secours (ignoré par git). `sim_out/` : sortie du simulateur (ignorée, régénérable).

Ensuite, remplir `contracts.py` (à la racine) avec les vraies données. Voir CLAUDE.md §4, §7, §8.

## Whoop (en local)

1. https://developer-dashboard.whoop.com → créer une Team → Create App.
   Scopes : `read:recovery read:sleep read:cycles read:profile` (+ `offline`).
   Redirect URI : `http://localhost:8000/oauth/whoop/callback`.
2. Mettre `WHOOP_CLIENT_ID` et `WHOOP_CLIENT_SECRET` dans `.env`.
3. Depuis la racine du repo :

```bash
python -m data.whoop login            # navigateur → accepter (port 8000 libre)
python -m data.whoop fetch --days 90  # → data/raw/whoop_{recovery,sleep,cycle,daily}.json
python -m data.whoop daily            # reconstruit whoop_daily.json depuis les exports (hors ligne)
```

## Simulateur

```bash
python -m data.simulate                                          # fourchettes WHOOP plausibles
python -m data.simulate --calibrate data/raw/whoop_daily.json    # recentré sur de vraies données
python -m data.simulate --clickhouse                             # + chargement ClickHouse (CLICKHOUSE_URL)
```

| Équipe | n | Histoire pour la démo |
|---|---|---|
| M&A | 14 + `persona_demo` | se dégrade sur les 3 dernières semaines (réunions ajoutées tard, +40 %) |
| Private Equity | 12 | un closing (rush) en semaines 3-4 |
| Conseil Stratégie | 12 | règle « pas d'ajout le jour même après 17h » depuis 4 semaines → récupère mieux |
| Leveraged Finance | 8 | pile au seuil n ≥ 8 |
| Restructuring | 4 | < 8 : doit être masquée par la requête SQL de la vue RH |

Chaque personne a sa propre baseline et une sensibilité dominante (calls de dernière minute, réunions après 20h, volume de mails…). `sim_out/truth.json` donne la vérité terrain, utile pour vérifier que les analytics retrouvent le bon driver. Rien de personnel n'est sorti du calibrage : seulement des moyennes et écarts-types.
