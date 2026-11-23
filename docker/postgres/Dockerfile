FROM pgvector/pgvector:0.8.0-pg17

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       postgresql-17-postgis-3 \
       postgresql-17-postgis-3-scripts \
    && rm -rf /var/lib/apt/lists/*

# Alinha o binário do PostgreSQL 17 e pgvector à mesma minor version do postgis-3
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       postgresql-17 \
       postgresql-17-pgvector \
    && rm -rf /var/lib/apt/lists/*
