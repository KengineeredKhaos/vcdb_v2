#!/usr/bin/env bash
# source scripts/env.test.sh
set -uo pipefail

export VCDB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$VCDB_ROOT"

# venv (fixed path)
source "$VCDB_ROOT/bin/activate"

# python path & flask
export PYTHONPATH="$VCDB_ROOT:$VCDB_ROOT/tests"
export FLASK_APP="manage_vcdb.py"
export FLASK_RUN_FROM_CLI="true"

# test DB (in-memory; switch to instance/test.db if you prefer)
mkdir -p "$VCDB_ROOT/instance" "$VCDB_ROOT/app/logs"
export SQLALCHEMY_DATABASE_URI="sqlite:///:memory:"
export FLASK_ENV="testing"
export VCDB_ENV="test"

echo "[vcdb env] test -> $SQLALCHEMY_DATABASE_URI"
echo "[vcdb path] test -> $PYTHONPATH"
