-- SARVEX PostgreSQL / PostGIS / pgvector bootstrap.
-- Runs once when the container initialises its data directory.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Ensure the application role can create objects in the public schema.
GRANT ALL PRIVILEGES ON DATABASE sarvex TO sarvex;
GRANT USAGE, CREATE ON SCHEMA public TO sarvex;
