-- Runs once when the Postgres data volume is first created.
-- The dev database (uhnime) already exists via POSTGRES_DB.
-- Migrations also enable pg_trgm (F-002); doing it here keeps a fresh
-- container usable before any migration has run.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Separate database for pytest. Tests never touch the dev database.
CREATE DATABASE uhnime_test;
\connect uhnime_test
CREATE EXTENSION IF NOT EXISTS pg_trgm;
