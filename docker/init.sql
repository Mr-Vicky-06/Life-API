-- Runs once when the container is first created.
-- Creates the pgvector extension and the read-only role.
-- View grants happen in Alembic migrations (views don't exist yet here).

CREATE EXTENSION IF NOT EXISTS vector;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'life_ro') THEN
    CREATE ROLE life_ro WITH LOGIN PASSWORD 'life_ro' NOSUPERUSER NOCREATEDB NOCREATEROLE;
  END IF;
END
$$;

GRANT CONNECT ON DATABASE life TO life_ro;
GRANT USAGE ON SCHEMA public TO life_ro;

