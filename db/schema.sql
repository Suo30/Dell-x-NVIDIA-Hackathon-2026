-- Frozen contract: MASTER_CONTEXT.md section 9. Change only by PR to that file.
CREATE TABLE IF NOT EXISTS candidates (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, profile_json TEXT NOT NULL,
  consent_auto INTEGER NOT NULL DEFAULT 1, synthetic INTEGER NOT NULL DEFAULT 1,
  updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS roles (
  id TEXT PRIMARY KEY, company TEXT NOT NULL, paid INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL, public_json TEXT NOT NULL, private_json TEXT NOT NULL,
  created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, source TEXT NOT NULL, company TEXT, title TEXT, url TEXT,
  location TEXT, description TEXT, role_id TEXT, requirements_json TEXT,
  sponsorship INTEGER, clearance TEXT, pay TEXT, paid INTEGER NOT NULL DEFAULT 0,
  first_seen TEXT NOT NULL, notified INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS matches (
  job_id TEXT, candidate_id TEXT, score REAL, route TEXT, detail_json TEXT,
  created TEXT, PRIMARY KEY (job_id, candidate_id));
CREATE TABLE IF NOT EXISTS applications (
  job_id TEXT, candidate_id TEXT, status TEXT, created TEXT,
  PRIMARY KEY (job_id, candidate_id));
