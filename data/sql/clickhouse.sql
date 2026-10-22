-- Séries temporelles (CLAUDE.md §7). Jamais de contenu : ni titre, ni corps.
CREATE TABLE IF NOT EXISTS work_events (
  user_id String, team_id String,
  ts DateTime, end_ts Nullable(DateTime),
  kind LowCardinality(String),      -- meeting | email_in | email_out | presence_green
  created_ts Nullable(DateTime),    -- meetings : date de création
  n_attendees UInt16 DEFAULT 0,
  is_external UInt8 DEFAULT 0,
  status LowCardinality(String) DEFAULT 'confirmed',
  source LowCardinality(String)     -- gcal | sim
) ENGINE = MergeTree ORDER BY (user_id, ts);

CREATE TABLE IF NOT EXISTS recovery_daily (
  user_id String, team_id String, date Date,
  recovery Float32, hrv Float32, rhr Float32,
  sleep_h Float32, sleep_consistency Float32,
  bedtime Nullable(DateTime), strain Float32,
  source LowCardinality(String)     -- whoop | sim
) ENGINE = ReplacingMergeTree ORDER BY (user_id, date);
