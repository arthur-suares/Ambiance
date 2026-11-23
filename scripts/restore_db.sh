#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "Erro: arquivo .env não encontrado na raiz do projeto." >&2
  echo "Execute primeiro:" >&2
  echo "  cp .env.example .env" >&2
  echo "e edite PG_PASSWORD (e OPENROUTER_API_KEY, se for usar o chat) no .env." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

PG_USER="${PG_USER:-rag}"
PG_DATABASE="${PG_DATABASE:-trase_rag}"
RELEASE_TAG="${AGRO_DATA_RELEASE:-data-v1}"
REPO="arthur-suares/Ambiance"
DEFAULT_DUMP="data/backups/agro_full.dump"
DUMP_FILE="${1:-$DEFAULT_DUMP}"

echo "[1/5] Subindo containers Docker (postgres + pgadmin)..."
docker compose up -d

echo "[2/5] Aguardando PostgreSQL ficar saudável..."
for _ in $(seq 1 40); do
  if docker exec trase-rag-postgres pg_isready -U "$PG_USER" -d "$PG_DATABASE" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if ! docker exec trase-rag-postgres pg_isready -U "$PG_USER" -d "$PG_DATABASE" >/dev/null 2>&1; then
  echo "Erro: PostgreSQL não respondeu a tempo." >&2
  exit 1
fi

if [ ! -f "$DUMP_FILE" ]; then
  if [ -n "${1:-}" ]; then
    echo "Erro: arquivo de dump não encontrado: $DUMP_FILE" >&2
    exit 1
  fi
  echo "[3/5] Baixando $DEFAULT_DUMP da Release $RELEASE_TAG..."
  mkdir -p "$(dirname "$DEFAULT_DUMP")"
  if command -v gh >/dev/null 2>&1; then
    gh release download "$RELEASE_TAG" -R "$REPO" -p agro_full.dump -D "$(dirname "$DEFAULT_DUMP")" --clobber
  elif command -v curl >/dev/null 2>&1; then
    curl -fL "https://github.com/$REPO/releases/download/$RELEASE_TAG/agro_full.dump" -o "$DEFAULT_DUMP"
  else
    echo "Erro: instale 'gh' (GitHub CLI) ou 'curl', ou baixe manualmente agro_full.dump para $DEFAULT_DUMP." >&2
    exit 1
  fi
else
  echo "[3/5] Usando dump local: $DUMP_FILE"
fi

echo "[4/5] Preparando extensões, role agro_ro e limpando schemas alvo..."
docker exec -i trase-rag-postgres psql -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DATABASE" <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS postgis;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agro_ro') THEN
    CREATE ROLE agro_ro NOLOGIN;
  END IF;
END $$;

DROP SCHEMA IF EXISTS gold CASCADE;
DROP SCHEMA IF EXISTS agro CASCADE;
DROP TABLE IF EXISTS public.chunks CASCADE;
DROP TABLE IF EXISTS public.documents CASCADE;
SQL

echo "[5/5] Restaurando banco a partir de $DUMP_FILE (pode levar ~1-3 minutos)..."
docker exec -i trase-rag-postgres pg_restore \
  -U "$PG_USER" \
  -d "$PG_DATABASE" \
  --no-owner \
  --no-privileges \
  --exit-on-error < "$DUMP_FILE"

docker exec -i trase-rag-postgres psql -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DATABASE" <<'SQL'
GRANT USAGE ON SCHEMA agro, gold, public TO agro_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA agro, gold, public TO agro_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA agro GRANT SELECT ON TABLES TO agro_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA gold GRANT SELECT ON TABLES TO agro_ro;
SQL

echo ""
echo "Restauração concluída! Resumo das tabelas:"
docker exec -i trase-rag-postgres psql -U "$PG_USER" -d "$PG_DATABASE" <<'SQL'
SELECT 'public.documents' AS tabela, COUNT(*) AS linhas FROM public.documents
UNION ALL SELECT 'public.chunks', COUNT(*) FROM public.chunks
UNION ALL SELECT 'agro.dim_municipios', COUNT(*) FROM agro.dim_municipios
UNION ALL SELECT 'agro.fato_trase_fluxos', COUNT(*) FROM agro.fato_trase_fluxos
UNION ALL SELECT 'agro.fato_inpe_deter', COUNT(*) FROM agro.fato_inpe_deter
UNION ALL SELECT 'agro.fato_seeg_emissoes', COUNT(*) FROM agro.fato_seeg_emissoes
UNION ALL SELECT 'gold.mv_territorio_municipal_ano', COUNT(*) FROM gold.mv_territorio_municipal_ano;
SQL
