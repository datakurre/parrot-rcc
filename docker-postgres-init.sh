#!/bin/bash
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL

	CREATE USER zeebe_monitor WITH PASSWORD 'zeebe_monitor';
	CREATE DATABASE zeebe_monitor;
	GRANT ALL PRIVILEGES ON DATABASE zeebe_monitor TO zeebe_monitor;

	CREATE USER zeebe_tasklist WITH PASSWORD 'zeebe_tasklist';
	CREATE DATABASE zeebe_tasklist;
	GRANT ALL PRIVILEGES ON DATABASE zeebe_tasklist TO zeebe_tasklist;

	CREATE USER zeebe_play WITH PASSWORD 'zeebe_play';
	CREATE DATABASE zeebe_play;
	GRANT ALL PRIVILEGES ON DATABASE zeebe_play TO zeebe_play;

	CREATE USER zeebe_api WITH PASSWORD 'zeebe_api';
	CREATE DATABASE zeebe_api;
	GRANT ALL PRIVILEGES ON DATABASE zeebe_api TO zeebe_api;

EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "zeebe_api" <<-EOSQL

    CREATE EXTENSION IF NOT EXISTS pgcrypto;

EOSQL