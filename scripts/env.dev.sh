#!/usr/bin/env bash
# source scripts/env.dev.sh
set -uo pipefail

export VCDB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$VCDB_ROOT"

# venv (fixed path)
source "$VCDB_ROOT/bin/activate"

# python path & flask
export PYTHONPATH="$VCDB_ROOT"
export FLASK_APP="manage_vcdb.py"
export FLASK_RUN_FROM_CLI="true"

# dev DB (file-backed)
mkdir -p "$VCDB_ROOT/instance" "$VCDB_ROOT/app/logs"
export SQLALCHEMY_DATABASE_URI="sqlite:///$VCDB_ROOT/instance/dev.db"
export FLASK_ENV="development"
export VCDB_ENV="dev"

echo "[vcdb env] dev → $SQLALCHEMY_DATABASE_URI"
