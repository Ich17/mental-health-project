# Brancher un vrai compte Google (Calendar + Gmail)

Durée : environ 15 minutes. À faire une seule fois, par la personne qui gère le compte de démo.
Sans ça, tout marche quand même en mode `mock` (données synthétiques).

## 1. Créer le projet Google Cloud
1. Aller sur https://console.cloud.google.com et se connecter.
2. En haut à gauche, cliquer sur le sélecteur de projet → **Nouveau projet**.
3. Nom : `baseline-hackathon` → **Créer**, puis sélectionner ce projet.

## 2. Activer les deux API
1. Menu ☰ → **API et services** → **Bibliothèque**.
2. Chercher **Google Calendar API** → **Activer**.
3. Revenir à la bibliothèque, chercher **Gmail API** → **Activer**.

## 3. Écran de consentement OAuth
1. Menu ☰ → **API et services** → **Écran de consentement OAuth** (ou « Google Auth Platform »).
2. **Commencer** / type d'utilisateur **Externe** → Créer.
3. Nom de l'application : `Baseline` ; e-mail d'assistance et e-mail du développeur : le vôtre.
4. **Accès aux données / Champs d'application** → **Ajouter des champs d'application** :
   - `https://www.googleapis.com/auth/calendar.readonly`
   - `https://www.googleapis.com/auth/gmail.metadata`
   - (optionnel, pour que l'agent crée des blocs « Occupé ») `https://www.googleapis.com/auth/calendar.events`
5. **Audience / Utilisateurs test** → **Ajouter des utilisateurs** : les adresses Gmail de l'équipe
   qui se connecteront (max 100). Laisser l'application en mode **Test** : pas besoin de validation Google.

> `gmail.metadata` est un scope « restreint » : en production il faudrait un audit Google.
> En mode Test avec des utilisateurs test, il fonctionne (Google affiche juste un avertissement
> « application non validée » → **Continuer**).

## 4. Créer l'identifiant OAuth
1. Menu ☰ → **API et services** → **Identifiants** → **Créer des identifiants** → **ID client OAuth**.
2. Type d'application : **Application de bureau** (Desktop app). Nom : `baseline-local` → **Créer**.
3. Copier le **Client ID** et le **Client secret** dans votre `.env` (jamais dans git) :
   ```
   GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=xxxx
   PSEUDONYM_SALT=une-longue-chaine-au-hasard
   ```
   (Alternative : télécharger le JSON et le poser dans `.secrets/credentials.json`.)

## 5. Lancer l'ingestion
```bash
source .venv/bin/activate
python -m data.ingest google --days 90
```
Un onglet s'ouvre : se connecter avec un compte **utilisateur test**, accepter. Le jeton est gardé
dans `.secrets/google_token.json` (ignoré par git) ; les fois suivantes, plus besoin de se connecter.
Le résultat est sauvegardé dans `data/raw/work_events_google.jsonl` (plan B si l'OAuth casse en démo).

## Ce qui est lu / ce qui ne l'est jamais
| Lu | Jamais lu ni stocké |
|---|---|
| Début, fin, date de création des réunions | Titre, description, lieu des réunions |
| Nombre d'invités, interne/externe (domaine) | Adresses des invités / destinataires |
| Heure d'envoi/réception des mails, nb de destinataires | Sujet, corps, pièces jointes des mails |

Le code demande à Google uniquement ces champs (paramètre `fields`), et l'identifiant de la
personne est remplacé par un pseudonyme (HMAC avec `PSEUDONYM_SALT`).

## En cas de problème
- **`access_denied` / « app non validée » bloquante** : le compte n'est pas dans les utilisateurs test (étape 3.5).
- **`invalid_scope` ou scopes changés** : supprimer `.secrets/google_token.json` et relancer.
- **`redirect_uri_mismatch`** : l'identifiant n'est pas de type « Application de bureau » (étape 4.2).
