-- rbac_sqlite.sql
PRAGMA foreign_keys = ON;

-- ROLES
CREATE TABLE IF NOT EXISTS roles (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  name         TEXT NOT NULL UNIQUE,
  description  TEXT,
  created_at   TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

-- USERS
CREATE TABLE IF NOT EXISTS users (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  email          TEXT NOT NULL,
  password_hash  TEXT NOT NULL,
  is_active      INTEGER NOT NULL DEFAULT 1,
  created_at     TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
  updated_at     TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
  last_login_at  TEXT
);

-- Case-insensitive uniqueness for email (works well for ASCII emails)
CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower_key ON users (lower(email));

-- USER_ROLES (M2M)
CREATE TABLE IF NOT EXISTS user_roles (
  user_id    INTEGER NOT NULL,
  role_id    INTEGER NOT NULL,
  granted_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
  PRIMARY KEY (user_id, role_id),
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
);

-- Seeds (replace hashes later with real ones)
INSERT INTO roles (name, description) VALUES
  ('admin',  'Administrator (full control)'),
  ('user',   'Standard authenticated user'),
  ('viewer', 'Read-only')
ON CONFLICT(name) DO NOTHING;

INSERT INTO users (email, password_hash) VALUES
  ('admin@example.com',  '!replace-with-real-hash'),
  ('user@example.com',   '!replace-with-real-hash'),
  ('viewer@example.com', '!replace-with-real-hash')
ON CONFLICT(lower(email)) DO NOTHING;

INSERT INTO user_roles (user_id, role_id)
SELECT u.id, r.id FROM users u JOIN roles r ON r.name='admin'
WHERE lower(u.email)='admin@example.com'
ON CONFLICT DO NOTHING;

INSERT INTO user_roles (user_id, role_id)
SELECT u.id, r.id FROM users u JOIN roles r ON r.name='user'
WHERE lower(u.email)='user@example.com'
ON CONFLICT DO NOTHING;

INSERT INTO user_roles (user_id, role_id)
SELECT u.id, r.id FROM users u JOIN roles r ON r.name='viewer'
WHERE lower(u.email)='viewer@example.com'
ON CONFLICT DO NOTHING;
