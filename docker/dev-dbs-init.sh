#!/bin/bash
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
	CREATE USER ${DATABASE_USER} WITH PASSWORD '${DATABASE_PASSWORD}';
	CREATE DATABASE ${DATABASE_NAME};
	CREATE DATABASE ${DATABASE_NAME}_test;
	ALTER DATABASE ${DATABASE_NAME} OWNER TO ${DATABASE_USER};
	ALTER DATABASE ${DATABASE_NAME}_test OWNER TO ${DATABASE_USER};
	GRANT USAGE, CREATE ON SCHEMA public TO ${DATABASE_USER};
EOSQL
