-- Mémoire long terme de l'agent (CLAUDE.md §7).
CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, name TEXT, team_id TEXT, created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS consents (user_id TEXT REFERENCES users(id), source TEXT, granted_at TIMESTAMPTZ DEFAULT now(), scopes TEXT);
CREATE TABLE IF NOT EXISTS hypotheses (id SERIAL PRIMARY KEY, user_id TEXT REFERENCES users(id), factor TEXT, effect_text TEXT, effect_size REAL, confidence TEXT, status TEXT, created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS experiments (id SERIAL PRIMARY KEY, user_id TEXT REFERENCES users(id), rule_text TEXT, start_date DATE, end_date DATE, baseline_recovery REAL, result_recovery REAL, verdict TEXT, created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS actions (id SERIAL PRIMARY KEY, user_id TEXT REFERENCES users(id), kind TEXT, payload JSONB, status TEXT CHECK (status IN ('proposed','accepted','rejected','done')), created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS feedback (id SERIAL PRIMARY KEY, user_id TEXT REFERENCES users(id), action_id INT REFERENCES actions(id), rating INT, comment TEXT, created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS team_rules (id SERIAL PRIMARY KEY, team_id TEXT, rule_text TEXT, start_date DATE, measured_effect TEXT, created_at TIMESTAMPTZ DEFAULT now());
