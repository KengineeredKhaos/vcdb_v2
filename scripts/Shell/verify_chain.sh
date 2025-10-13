#!/usr/bin/env bash
# scripts/verify_chain.sh
set -eo pipefail
: "${BASE:=http://127.0.0.1:5000}"
: "${JAR:=/tmp/vcdb-verify.$$}.cookies"

echo "Verifying ledger hash-chain integrity…"

# optional: hit the export endpoint (requires auth)
csrf=$(curl -s -c "$JAR" -b "$JAR" "$BASE/auth/login" \
  | sed -n 's/.*name="csrf_token" value="\([^"]*\)".*/\1/p' | head -n1)
curl -s -c "$JAR" -b "$JAR" -X POST \
  -d "login=user@example.com" -d "password=password" -d "csrf_token=$csrf" \
  "$BASE/auth/login" -o /dev/null

curl -s -b "$JAR" "$BASE/transactions/export.jsonl" -o /tmp/ledger-export.jsonl || true

# run the Python verifier (DB-backed)
python scripts/verify_ledger_chain.py

rm -f "$JAR" 2>/dev/null || true
