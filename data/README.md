# data/ : récupérer les vraies données

- `gcal.py` (à créer) : Google Calendar → début, fin, nb d'invités, interne/externe, date de création. Jamais le titre ni la description.
- `whoop.py` : Whoop → récupération, HRV, FC repos, sommeil, strain (une ligne par jour, format `recovery_daily`).
- `check_whoop.py` : bilan qualité + nettoyage (jours manquants, valeurs impossibles, siestes, fuseaux) → `whoop_daily_clean.json`. Sans pandas.
- `simulate.py` : ~50 profils fictifs (agenda, mails, présence, récupération) pour la vue RH et le profil de secours `persona_demo`.
- `clickhouse.sql` : les tables où ranger ces données.
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
