# data/exemples : voir les données sans rien installer

Cliquer sur un fichier `.csv` : GitHub l'affiche comme un tableau.
Aucune donnée personnelle ici (simulateur inventé, Radoslaw et Viva publics).

Le simulateur est **calibré sur Radoslaw** pour la forme des journées : courbe des heures d'envoi
et nombre de destinataires (86 % des mails à une seule personne). Les volumes et la dérive restent
ceux de la cible (juniors banque / conseil).

| Fichier | Contenu |
|---|---|
| `simulateur_extrait.csv` | **À ouvrir en premier.** Une semaine (12 → 18 oct.) de 2 salariés fictifs : `emp01` normal, `emp02` en dérive (réunions et mails le soir). Mails reçus retirés pour la lisibilité. |
| `simulateur_verite.csv` | Qui dérive et depuis quand (10 personnes : 3 dérives, 1 rush ponctuel, 6 normales). |
| `simulateur_complet.csv` | Le dataset complet du simulateur : 33 580 lignes, 10 personnes, 23 juil. → 21 oct. 2026 (trop gros pour l'aperçu GitHub : bouton « Download »). |
| `radoslaw_extrait.csv` | Février 2010 d'un vrai salarié de l'usine Radoslaw (mails seulement). |
| `viva_extrait.csv` | 3 personnes × 35 semaines de l'échantillon Microsoft Viva (une ligne = une semaine). |

## Les colonnes (simulateur et Radoslaw)

| Colonne | Sens |
|---|---|
| `user_id` | personne (pseudonyme) |
| `team_id` | équipe |
| `ts` / `end_ts` | début / fin (heure locale) |
| `kind` | `meeting`, `email_out` (envoyé), `email_in` (reçu) |
| `created_ts` | date de création de la réunion (réunion « de dernière minute » si < 24 h avant) |
| `n_attendees` | nb d'invités ou de destinataires |
| `is_external` | 1 si quelqu'un d'extérieur à l'entreprise |
| `status` | `confirmed`, `cancelled`, `declined` |
| `duration_min` | durée en minutes (réunions) |
| `is_after_hours` | 1 si hors horaires (avant 8h / après 19h ; usine Radoslaw : 7h-16h) |
| `is_weekend` | 1 si samedi ou dimanche |
| `source` | `sim`, `radoslaw` |

Ces fichiers sont une copie figée. Pour régénérer : `python -m data.ingest mock` (ou `radoslaw`, `viva`), sortie dans `data/raw/`.
