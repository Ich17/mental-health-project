-- Séries temporelles (CLAUDE.md §7). Jamais de contenu : ni titre, ni corps.
CREATE TABLE IF NOT EXISTS work_events (
  user_id String, team_id String,
  ts DateTime, end_ts Nullable(DateTime),
  kind LowCardinality(String),      -- meeting | email_in | email_out | presence_green
  created_ts Nullable(DateTime),    -- meetings : date de création
  n_attendees UInt16 DEFAULT 0,
  is_external UInt8 DEFAULT 0,
  status LowCardinality(String) DEFAULT 'confirmed',
  source LowCardinality(String)     -- gcal | gmail | sim
) ENGINE = MergeTree ORDER BY (user_id, ts);

CREATE TABLE IF NOT EXISTS recovery_daily (
  user_id String, team_id String, date Date,
  recovery Float32, hrv Float32, rhr Float32,
  sleep_h Float32, sleep_consistency Float32,
  bedtime Nullable(DateTime), strain Float32,
  source LowCardinality(String)     -- whoop | sim
) ENGINE = ReplacingMergeTree ORDER BY (user_id, date);

-- Champs dérivés ajoutés par les connecteurs gcal / gmail / sim (data/events.py).
-- Si la table existe déjà sur Aiven, lancer une fois :
--   ALTER TABLE work_events ADD COLUMN IF NOT EXISTS duration_min UInt16 DEFAULT 0,
--     ADD COLUMN IF NOT EXISTS is_after_hours UInt8 DEFAULT 0,
--     ADD COLUMN IF NOT EXISTS is_weekend UInt8 DEFAULT 0;
ALTER TABLE work_events ADD COLUMN IF NOT EXISTS duration_min UInt16 DEFAULT 0;
ALTER TABLE work_events ADD COLUMN IF NOT EXISTS is_after_hours UInt8 DEFAULT 0;
ALTER TABLE work_events ADD COLUMN IF NOT EXISTS is_weekend UInt8 DEFAULT 0;

-- Indicateurs hebdomadaires au format Microsoft Viva Insights (data/viva.py).
-- wellbeing / workload / work_life_balance : enquête 1-5, validation uniquement,
-- jamais exposés individuellement.
CREATE TABLE IF NOT EXISTS work_weekly (
  user_id String, team_id String, level LowCardinality(String), week Date,
  source LowCardinality(String),        -- viva
  collaboration_h Nullable(Float32), meeting_h Nullable(Float32), meetings Nullable(Float32),
  conflicting_meeting_h Nullable(Float32), email_h Nullable(Float32), emails_sent Nullable(Float32),
  chat_h Nullable(Float32), call_h Nullable(Float32), after_hours_h Nullable(Float32),
  weekend_h Nullable(Float32), multitasking_h Nullable(Float32),
  collaboration_span_h Nullable(Float32), active_connected_h Nullable(Float32),
  wellbeing Nullable(Float32), workload Nullable(Float32), work_life_balance Nullable(Float32)
) ENGINE = ReplacingMergeTree ORDER BY (user_id, week);
