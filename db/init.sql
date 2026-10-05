-- Runs once when the Postgres container is first created (docker-entrypoint-initdb.d).
-- Tables, including the HNSW cosine index on chunks.embedding, are created by the API on
-- startup from SQLAlchemy metadata (backend/app/models.py). On Amazon RDS, run this
-- statement once as the master user; pgvector is a supported RDS extension.
CREATE EXTENSION IF NOT EXISTS vector;
