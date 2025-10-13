#!/usr/bin/env bash
# Simple auth smoke test for vcdb-v2
# Usage:
#   ./scripts/smoke_auth.sh
#   BASE=http://127.0.0.1:5000 ./scripts/smoke_auth.sh
set -u

BASE="${BASE:-${1:-http://localhost:5000}}"
echo "Base: $BASE"

ROUTES=(
  "/customers/hello"
  "/calendar/hello"
  "/governance/hello"
  "/inventory/hello"
  "/resources/hello"
  "/sponsors/hello"
  "/transactions/hello"
)

now(){ date +%H:%M:%S; }

# GET a path; prints "CODE|LOCATION" (LOCATION may be empty)
get(){
  local path="$1"; local with_cookie="${2:-}"
  local headers rc=0
  if [[ -n "$with_cookie" ]]; then
    headers=$(curl -sS -D - -o /dev/null -b "$COOK" "$BASE$path") || rc=$?
  else
    headers=$(curl -sS -D - -o /dev/null "$BASE$path") || rc=$?
  fi
  if (( rc != 0 )); then
    echo "ERR|curl_exit_$rc"; return 0
  fi
  local code loc
  code=$(awk 'NR==1{print $2}' <<<"$headers")
  loc=$(awk '/^[Ll]ocation:/{print $2}' <<<"$headers" | tr -d '\r')
  echo "${code:-NONE}|${loc:-}"
}

# Login as a user; creates a fresh cookie jar in $COOK
post_login(){
  local email="$1" pass="${2:-test123}"
  COOK="$(mktemp)"
  local rc=0 headers code
  # prefetch to initialize session cookie jar
  curl -sS -c "$COOK" "$BASE/auth/login" >/dev/null || rc=$?
  if (( rc != 0 )); then echo "FAIL  $(now)  login prefetch exit=$rc"; return 1; fi
  # post credentials (don’t follow redirects)
  headers=$(curl -sS -D - -o /dev/null -c "$COOK" -b "$COOK" \
    -X POST -d "email=$email&password=$pass" "$BASE/auth/login") || rc=$?
  if (( rc != 0 )); then echo "FAIL  $(now)  login post exit=$rc"; return 1; fi
  code=$(awk 'NR==1{print $2}' <<<"$headers")
  if [[ "$code" == "302" || "$code" == "303" || "$code" == "200" ]]; then
    echo "PASS  $(now)  login $email"
    return 0
  else
    echo "FAIL  $(now)  login $email code=$code"
    return 1
  fi
}

check_expect_redirect_login(){
  local path="$1"
  IFS='|' read -r code loc <<<"$(get "$path")"
  if [[ "$code" == "302" && "$loc" == *"/auth/login"* ]]; then
    echo "PASS  $(now)  $path  got=302 -> $loc"
  else
    echo "FAIL  $(now)  $path  got=${code}|${loc:-none}"
  fi
}

check_expect_code(){
  local path="$1" want="$2"
  IFS='|' read -r code loc <<<"$(get "$path" cookie)"
  if [[ "$code" == "$want" ]]; then
    echo "PASS  $(now)  $path  got=$code want=$want"
  else
    echo "FAIL  $(now)  $path  got=$code want=$want ${loc:+redirect=$loc}"
  fi
}

# Health
IFS='|' read -r code loc <<<"$(get /healthz)"
if [[ "$code" == "200" ]]; then
  echo "PASS  $(now)  healthz 200"
else
  echo "FAIL  $(now)  healthz $code"
fi

echo "== Public =="
IFS='|' read -r code loc <<<"$(get /)"
if [[ "$code" == "200" ]]; then
  echo "PASS  $(now)  /  got=200 want=200"
else
  echo "FAIL  $(now)  /  got=$code want=200"
fi

echo "== Unauthenticated on protected (expect 302 -> /auth/login) =="
for p in "${ROUTES[@]}"; do
  check_expect_redirect_login "$p"
done

echo "== Viewer session (default expect 403) =="
post_login "viewer@example.com" "test123" >/dev/null || true
for p in "${ROUTES[@]}"; do
  check_expect_code "$p" "403"
done

echo "== User session (default expect 200) =="
post_login "user@example.com" "test123" >/dev/null || true
for p in "${ROUTES[@]}"; do
  check_expect_code "$p" "200"
done

echo "== Admin session (report only) =="
post_login "admin@example.com" "test123" >/dev/null || true
for p in "${ROUTES[@]}"; do
  IFS='|' read -r code loc <<<"$(get "$p" cookie)"
  echo "  $(now)  $p  code=${code}${loc:+|$loc}"
done
