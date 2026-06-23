-- Runs automatically inside the `postgre_catalogue` database on first startup
-- (database created by POSTGRES_DB env var in docker-compose)

CREATE EXTENSION IF NOT EXISTS vector;
