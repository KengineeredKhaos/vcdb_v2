-- === Parties (people) ===
CREATE TABLE IF NOT EXISTS parties (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  kind        TEXT NOT NULL CHECK (kind IN ('person','org')),
  created_at  TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
  updated_at  TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

-- Minimal "person" profile (PII) — plaintext for now (we’ll encrypt later)
CREATE TABLE IF NOT EXISTS party_person (
  party_id   INTEGER PRIMARY KEY,
  namelast   TEXT NOT NULL,
  namefirst  TEXT NOT NULL,
  last4      TEXT,                   -- last 4 of SSN or similar
  dob        TEXT,                   -- ISO 'YYYY-MM-DD'
  branch     TEXT,                   -- usa, usmc, usn, usaf, ussf, uscg, civ
  dd214      INTEGER NOT NULL DEFAULT 0,
  vacard     INTEGER NOT NULL DEFAULT 0,
  statedl    INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY (party_id) REFERENCES parties(id) ON DELETE CASCADE
);

-- Optional: basic contact data (dev-friendly; we can normalize later)
CREATE TABLE IF NOT EXISTS party_contact (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  party_id   INTEGER NOT NULL,
  phone1     TEXT,
  phone2     TEXT,
  email      TEXT,
  website    TEXT,
  social     TEXT,
  addr1      TEXT,
  addr2      TEXT,
  city       TEXT,
  state      TEXT,
  zip        TEXT,
  FOREIGN KEY (party_id) REFERENCES parties(id) ON DELETE CASCADE
);

-- === Users: add username & link to person (party) ===
ALTER TABLE users ADD COLUMN username   TEXT;
ALTER TABLE users ADD COLUMN person_id  INTEGER REFERENCES parties(id);

-- Case-insensitive unique usernames (NULLs allowed until we backfill)
CREATE UNIQUE INDEX IF NOT EXISTS users_username_lower_key ON users (lower(username));
