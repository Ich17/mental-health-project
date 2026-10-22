# Baseline — agent anti-épuisement (Hackathon Accel × Aiven, 1 journée)

> Nom de travail : **Baseline** (à changer si l'équipe préfère). Ce fichier est le brief du projet pour Claude Code : contexte, contraintes, architecture, priorités. Le lire en entier avant de coder.

---

## 1. Le challenge (règles officielles)

> Build a working product where one or more agents depend on data to deliver value for a specific user. That could mean querying large datasets, reacting to event streams, keeping long-term memory, combining many sources or improving over time from past runs. You choose the customer and the problem.
> Use any models, frameworks and tools you like. Deploy your app to our sponsor Aiven's Runtime, and use their managed data infrastructure for your data layer where relevant (PostgreSQL, ClickHouse, Valkey, OpenSearch and more).
> Strong teams need more than code. Product thinking, design and a credible route to first users all count.

Jury : Accel (VC). Ils jugent une **démo qui marche sur de la vraie donnée**, un **utilisateur précis**, le **design** et une **route crédible vers les premiers utilisateurs**.

---

## 2. Le produit en une phrase

**« Ta Whoop sait que tu es épuisé. Ton agenda sait pourquoi. Baseline relie les deux et agit avant le burn-out. »**

- **Utilisateur** : juniors en banque d'affaires / private equity / conseil (grosses semaines, heures déclarées fausses, n'osent pas demander d'aide).
- **Acheteur** : l'entreprise, comme avantage salarié (abonnement par salarié). Plus tard : mutuelles / assureurs prévoyance comme canal (ils paient les arrêts).
- **Problème** : tout ce qui existe sur le burn-out est curatif (après la casse). Personne ne détecte en amont, et les apps de chat santé mentale échouent car le salarié doit faire le premier pas.

### Ce que fait l'agent
1. Reçoit les **métadonnées de travail** (jamais le contenu) : réunions, réunions ajoutées le jour même, mails reçus, temps « vert » sur Teams…
2. Reçoit les **données de récupération** de la montre (Whoop / Garmin / Oura) : sommeil, HRV, FC au repos, score de récupération.
3. Apprend **ce qui épuise cette personne** (« tes calls ajoutés le jour même te coûtent ~25 min de sommeil »), en comparant chacun à **sa propre baseline**.
4. **Prévoit** la semaine à venir (jours rouges) à partir de l'agenda futur.
5. **Agit** : propose de bloquer des créneaux (déjeuner, sport, focus, séance psy) dans l'agenda avec un intitulé neutre « Occupé », après validation en 1 clic.
6. **Teste et apprend** : lance des « expériences personnelles » (ex. pas de réunion après 19h mardi/jeudi), mesure l'effet sur la récupération, garde ce qui marche (= « improving over time from past runs »).

### Les 3 niveaux (règle d'or : l'entreprise est alertée sur des **causes**, jamais sur des **personnes**)
1. **Privé** — conseils + actions agenda. Seul le salarié voit.
2. **Collectif anonyme (vue RH)** — tendances d'équipe uniquement si **n ≥ 8 personnes** (sinon on remonte au département), valeurs lissées (pas de comptes exacts, éviter la déduction par différence). Exemple : « Équipe M&A : majorité en dette de récupération depuis 3 semaines. Cause n°1 : réunions ajoutées après 18h (+40 %). Règle suggérée : pas d'ajout le jour même après 17h. » Puis mesure de l'effet de la règle.
3. **Au choix du salarié** — si rouge plusieurs semaines, l'agent propose de rédiger un message factuel pour le manager ou le médecin du travail. Le salarié envoie ou pas.

### Différenciation
- Whoop / Oura : voient le corps, conseils génériques, ignorent le travail.
- Microsoft Viva Insights : voit le travail (heures de réunion, mails hors horaires), ignore le corps, constate sans agir.
- Reclaim / Motion : optimisent la productivité, pas la récupération.
- **Baseline = croisement corps × travail + agent qui agit + apprentissage personnel.**

---

## 3. Contraintes NON négociables (privacy / AI Act)

- **Jamais de contenu** : pas de corps de mail, pas de texte de message, pas de titre de réunion stocké en clair au-delà de ce qui est nécessaire (on garde : début, fin, nb d'invités, interne/externe via domaine, date de création, date de modif, statut).
- **On mesure la fatigue / récupération, jamais les émotions** (l'AI Act interdit l'inférence d'émotions au travail à partir de données biométriques ; la fatigue physique est hors de cette définition). Vocabulaire produit : « récupération », « charge », « fatigue » — jamais « stress détecté », « humeur », « émotion ».
- **Aucune donnée individuelle ne remonte à l'employeur.** La vue RH ne lit que des agrégats, et le seuil **n ≥ 8 est appliqué dans la requête SQL elle-même** (pas dans le prompt de l'agent, pas dans le front).
- Les événements créés dans l'agenda ont le titre **« Occupé »** et la visibilité `private`. Le vrai motif n'est visible que dans l'app.
- L'agent **propose avant d'agir** (création d'événement uniquement après confirmation explicite).
- L'agent ne pose aucun diagnostic médical ; en cas de semaines rouges répétées il oriente (psy pris en charge par la mutuelle, médecin du travail).

---

## 4. Données : réel vs simulé

| Source | Méthode | Statut démo |
|---|---|---|
| Agenda | Google Calendar API (OAuth, mode test, utilisateurs test ajoutés à la main) | **Réel** (compte d'Ichane) |
| Récupération | WHOOP API v2 (OAuth, palier Sandbox = 10 membres sans approbation) | **Réel** (Whoop d'Ichane) |
| Mails reçus/envoyés | Simulé (Gmail `gmail.metadata` possible mais scope « restricted » → bonus seulement) | Simulé |
| Présence Teams | Impossible sans tenant entreprise | Simulé |
| Cohorte RH | ~40 faux salariés, 4 équipes, 8 semaines, corrélations charge→récup réalistes | Simulé |

Phrase pitch : « Mes données sont réelles ; côté entreprise on simule ce que Microsoft Graph fournirait, avec les mêmes garanties. »

**Plan B obligatoire** : sauvegarder dès le début l'export Whoop + agenda en JSON (`data/raw/`). Si l'OAuth casse ou si les données réelles ne montrent rien de net, on bascule sur un profil simulé réaliste (`persona_demo`).

### WHOOP API (vérifier les noms de champs sur developer.whoop.com/api)
- Dashboard : https://developer-dashboard.whoop.com (créer équipe → app → Client ID / Secret).
- Auth : `https://api.prod.whoop.com/oauth/oauth2/auth` — Token : `https://api.prod.whoop.com/oauth/oauth2/token`
- Base : `https://api.prod.whoop.com/developer`
- Scopes : `read:recovery read:sleep read:cycles read:profile` (+ `offline` si nécessaire pour le refresh token — vérifier).
- Endpoints : `GET /v2/recovery`, `GET /v2/activity/sleep`, `GET /v2/cycle` — pagination `limit` (max 25) + `nextToken`, filtres `start` / `end`.
- Pas de webhooks v2 documentés → polling (job planifié).
- Champs utiles (à confirmer) : recovery_score, hrv_rmssd_milli, resting_heart_rate ; sleep : début/fin, durée par stade, sleep_performance, sleep_consistency ; cycle : strain.

### Google Calendar API
- Scopes : `calendar.readonly` (lecture) + `calendar.events` (création des blocs).
- `events.list` avec `singleEvents=true`, `showDeleted=true`, `timeMin`/`timeMax` (−8 semaines → +2 semaines).
- **`created` vs `start`** → réunion « ajoutée le jour même » si `start - created < 24h`. `updated` + `status=cancelled` → déplacements/annulations.
- Interne vs externe : domaine des `attendees` vs domaine de l'utilisateur.

---

## 5. Architecture

```
Google Calendar ─┐
WHOOP ───────────┼─▶ Valkey (stream d'événements) ─▶ worker ─▶ ClickHouse
Simulateur ──────┘                                              │
(mails, Teams, cohorte RH)                                      ▼
                                          vues SQL : indicateurs / jour / user
                                                                │
                           Agent salarié (LLM + outils) ◀───────┤
                           Agent RH (LLM + outils)     ◀────────┘
                                   │       ▲
                                   ▼       │
                       PostgreSQL : mémoire (hypothèses, expériences,
                       actions, consentements, feedback)
                                   │
                                   ▼
                     App web (FastAPI + front) + écriture Google Calendar
```

### Services Aiven (chacun a un vrai rôle)
- **Valkey** — stream d'ingestion (`XADD` / consumer group) + cache. Coche « reacting to event streams ».
- **ClickHouse** — toutes les séries temporelles + calcul des indicateurs, baselines, corrélations, agrégats équipe. Coche « querying large datasets ».
- **PostgreSQL** — mémoire long terme de l'agent. Coche « long-term memory » + « improving over time ».
- **Aiven Runtime** — héberge l'app et les agents « à côté de la donnée ». Argument pitch : la donnée ne sort pas de l'environnement.
- (OpenSearch non nécessaire — ne pas le forcer. Kafka possible mais Valkey suffit.)

### Aiven Runtime — notes pratiques
- Déploiement depuis un **repo GitHub** avec `Dockerfile` (ou Docker Compose). Le compte GitHub doit être connecté à l'org Aiven.
- Les connexions aux services sont injectées en **variables d'environnement** via une intégration `application_service_credential` (ex. `DATABASE_URL`). Prévoir : `DATABASE_URL`, `CLICKHOUSE_URL`, `VALKEY_URL`.
- **Un push ne redéploie pas automatiquement** → Console : Overview → Actions → « Deploy latest commit ».
- Pas de cron documenté → le planificateur (APScheduler) tourne **dans l'API**.
- Écouter sur le port déclaré (`application.ports`), ex. 8000.

---

## 6. Stack applicative

- **Backend** : Python 3.12, FastAPI, `clickhouse-connect`, `psycopg` (v3), `redis` (client Valkey), `httpx`, `pandas`/`numpy` (stats), APScheduler, SDK `anthropic` (tool use).
- **Front** : simple et beau — soit React + Vite + Tailwind servi par FastAPI (build statique), soit Next.js. Graphiques : Recharts. Le design compte dans la note.
- **LLM** : Claude via SDK Anthropic (`ANTHROPIC_API_KEY`). Modèle configurable par env `LLM_MODEL`.
- Un seul compte de démo (pas d'auth multi-utilisateurs). `USER_ID=ichane` par défaut.

### Arborescence
```
/data        → Dev A : connecteurs (whoop.py, gcal.py), simulateur (simulate.py), schémas SQL, analytics
/agent       → Dev B : boucle agent, définition des outils, prompts, mémoire Postgres
/api         → FastAPI (routes, scheduler, OAuth callbacks)
/web         → Front
/data/raw    → exports JSON de secours (gitignore si données perso)
contracts.py → interface entre data et agent (voir §8)
Dockerfile, docker-compose.yml, .env.example, README.md
```

---

## 7. Schémas de données

### ClickHouse
```sql
CREATE TABLE work_events (
  user_id String, team_id String,
  ts DateTime, end_ts Nullable(DateTime),
  kind LowCardinality(String),      -- meeting | email_in | email_out | presence_green
  created_ts Nullable(DateTime),    -- meetings : date de création
  n_attendees UInt16 DEFAULT 0,
  is_external UInt8 DEFAULT 0,
  status LowCardinality(String) DEFAULT 'confirmed',
  source LowCardinality(String)     -- gcal | sim
) ENGINE = MergeTree ORDER BY (user_id, ts);

CREATE TABLE recovery_daily (
  user_id String, team_id String, date Date,
  recovery Float32, hrv Float32, rhr Float32,
  sleep_h Float32, sleep_consistency Float32,
  bedtime Nullable(DateTime), strain Float32,
  source LowCardinality(String)     -- whoop | sim
) ENGINE = ReplacingMergeTree ORDER BY (user_id, date);
```
Vue `daily_metrics` (par user, par jour) : `meeting_hours`, `n_meetings`, `last_minute_meetings` (start − created < 24h), `meetings_after_20h`, `meetings_before_8h30`, `back_to_back`, `longest_free_block_h`, `no_lunch_break`, `weekend_events`, `emails_in`, `emails_out_after_21h`, `green_hours`, `days_since_last_off`, jointe à `recovery_daily` sur J+1.

### PostgreSQL (mémoire)
```sql
users(id, name, team_id, created_at)
consents(user_id, source, granted_at, scopes)
hypotheses(id, user_id, factor, effect_text, effect_size, confidence, status, created_at, updated_at)
experiments(id, user_id, rule_text, start_date, end_date, baseline_recovery, result_recovery, verdict, created_at)
actions(id, user_id, kind, payload jsonb, status, created_at)   -- proposed | accepted | rejected | done
feedback(id, user_id, action_id, rating, comment, created_at)
team_rules(id, team_id, rule_text, start_date, measured_effect, created_at)
```
**Pré-remplir** une expérience terminée et une règle d'équipe avec effet mesuré, pour montrer la boucle d'apprentissage en démo.

---

## 8. Le contrat data ↔ agent (`contracts.py`)

Dev B code contre des **mocks** qui renvoient exactement ces exemples ; Dev A remplace par les vraies implémentations sans changer les signatures.

```python
def get_daily_metrics(user_id: str, days: int = 42) -> list[dict]:
    # [{"date": "2026-10-20", "meeting_hours": 6.5, "last_minute_meetings": 3,
    #   "meetings_after_20h": 2, "emails_in": 87, "green_hours": 10.2,
    #   "recovery": 34, "hrv": 41, "sleep_h": 6.1}, ...]

def get_drivers(user_id: str) -> list[dict]:
    # [{"factor": "last_minute_meetings", "label": "Calls ajoutés le jour même",
    #   "effect": "-25 min de sommeil par call", "effect_size": -0.42, "confidence": "moyenne"}, ...]

def forecast_week(user_id: str) -> list[dict]:
    # [{"date": "2026-10-29", "predicted_recovery": 28, "risk": "rouge",
    #   "reason": "4 calls après 20h"}, ...]

def get_free_slots(user_id: str, date: str) -> list[dict]:
    # [{"start": "2026-10-29T12:30:00", "end": "2026-10-29T13:30:00"}, ...]

def team_trends(team_id: str) -> dict:
    # {"team": "M&A", "n_bucket": "10-15", "share_in_debt": "majorité",
    #  "top_cause": "réunions ajoutées après 18h", "cause_change": "+40%",
    #  "trend": [{"week": "2026-W40", "avg_recovery": 52}, ...]}
    # Renvoie {"insufficient_group": true} si n < 8 (filtre dans la requête SQL).
```

### Analytics (code classique, pas LLM)
- Baseline perso : moyenne/écart-type glissants 28 jours → z-scores.
- Drivers : pour chaque indicateur du jour J vs récupération/HRV/sommeil à J+1, corrélation + régression simple, intervalle par bootstrap ; garder top 3. Présenter comme **hypothèses** (peu de données).
- Forecast : appliquer les coefficients perso aux indicateurs de l'agenda futur.
- Expériences : comparer la récupération moyenne pendant l'expérience vs baseline → verdict.

---

## 9. Les agents

Boucle tool-use standard (SDK Anthropic) : envoyer messages + tools → si `stop_reason == "tool_use"`, exécuter les outils, renvoyer `tool_result`, recommencer → sinon réponse finale.

### Agent salarié — outils
`get_daily_metrics`, `get_drivers`, `forecast_week`, `get_free_slots`, `get_memory` (hypothèses + expériences + feedback passés), `propose_block` (crée une action `proposed`), `create_calendar_block` (**uniquement** sur action acceptée ; titre « Occupé », visibilité privée), `start_experiment`, `evaluate_experiment`, `draft_message` (pour manager / médecin du travail, jamais envoyé automatiquement), `save_hypothesis`.

Déclencheurs : planificateur **dimanche 19h** (préparer la semaine), **chaque matin** (check du jour), et à la demande (chat / bouton dans l'app).

Prompt système (esprit) : tu es un agent anti-épuisement personnel ; tu parles de récupération et de charge, jamais d'émotions ; tu t'appuies sur les données via les outils, tu cites les chiffres ; tu proposes avant d'agir ; tu présentes les liens comme des hypothèses ; tu te souviens de ce qui a marché pour cette personne ; ton direct, bienveillant, bref.

### Agent RH — outils
`team_trends` (seul accès aux données — agrégats filtrés n ≥ 8), `get_team_rules`, `suggest_rule`, `measure_rule_effect`. Aucun outil n'expose de donnée individuelle.

---

## 10. Écrans (le design compte)

1. **Mon tableau de bord** — courbe charge vs récupération (6 semaines), top 3 causes en langage clair.
2. **Ma semaine prochaine** — jours prévus (vert/orange/rouge), actions proposées avec bouton « Bloquer » → écrit vraiment dans Google Calendar.
3. **Mes expériences** — expérience en cours / passées, effet mesuré.
4. **Vue RH** — tendances anonymes par équipe, règle suggérée, effet mesuré d'une règle appliquée.
5. **« Ce que l'agent voit / ne voit pas »** — écran confidentialité (réponse visuelle à l'objection « intrusif »).
6. (Bonus) Page d'inscription / waitlist pour récolter de vrais inscrits pendant la journée.

---

## 11. Priorités (couper dans cet ordre si retard)

- **P0 — le cœur de la démo** : Whoop + agenda réels dans ClickHouse → drivers → forecast → agent salarié qui propose et crée un bloc dans l'agenda → écrans 1 et 2 → déployé sur Aiven Runtime.
- **P1** : mémoire Postgres + expérience pré-remplie (écran 3), cohorte simulée + vue RH (écran 4), écran confidentialité (5), ingestion via Valkey stream.
- **P2** : agent RH complet, Gmail metadata réel, expériences lancées en live, waitlist, notifications.

## 12. Planning

| Heure | Quoi |
|---|---|
| 9h–10h | Comptes Aiven + clé LLM, repo GitHub, **hello world FastAPI déployé sur Runtime et connecté à Postgres**. Écrire `contracts.py` à deux. |
| 10h–13h | Dev A : connecteurs Whoop/GCal + export JSON de secours + simulateur + tables ClickHouse. Dev B : boucle agent sur mocks + mémoire Postgres + squelette front. |
| 12h30 | Synchro : `get_daily_metrics` réel branché. |
| 13h–15h | Drivers + forecast réels, création d'événement GCal, écrans branchés, vue RH. |
| 15h | Synchro : tout ce qui n'est pas branché est coupé. |
| 15h30 | **Gel des features.** Bugs, données de démo propres, pitch, 2 répétitions. |

## 13. Script de démo (2 min)

1. Problème (15 s) : les juniors mentent sur leurs heures, le burn-out n'est traité qu'après.
2. « Voici mes 6 dernières semaines réelles » → courbe + causes trouvées.
3. Semaine prochaine : jeudi rouge → l'agent propose de bloquer → clic → l'événement apparaît dans Google Calendar.
4. Mémoire : « la dernière expérience (pas de call après 19h) a fait +12 % de récupération ».
5. Vue RH : tendance anonyme + règle suggérée + effet mesuré, aucun nom.
6. Écran confidentialité + phrase Aiven : « l'agent tourne à côté de la donnée, rien ne sort ».
7. Premiers utilisateurs : X inscrits aujourd'hui (waitlist) + réseaux juniors banque/PE/conseil.

---

## 14. Consignes pour Claude Code

- Commencer par le **squelette déployable** (FastAPI + Dockerfile + `/health` + connexion Postgres via `DATABASE_URL`), avant toute feature.
- Toujours fournir `.env.example` à jour. Ne jamais committer de secrets ni de données perso (`data/raw/` dans `.gitignore`).
- Écrire `contracts.py` avec mocks en premier ; garder les signatures stables.
- Code simple et lisible, pas de sur-architecture : c'est un PoC d'une journée.
- Respecter strictement la section 3 (privacy) dans le code, pas seulement dans les prompts.
- Après chaque étape : dire ce qui marche, comment le tester, et la prochaine étape.
