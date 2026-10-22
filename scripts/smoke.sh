#!/usr/bin/env bash
# Usage: scripts/smoke.sh <base-url>
# Post-deploy checks from task 11 in docs/tasks.md.
set -euo pipefail

url="${1:?usage: scripts/smoke.sh <base-url>}"
url="${url%/}"
samples="${SAMPLES:-20}"
limit_ms="${LIMIT_MS:-200}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

# A free Render service sleeps when idle and takes about a minute to wake (spec Clarification 15).
curl -s -o /dev/null --max-time 120 --retry 5 --retry-all-errors "$url/healthz" ||
  fail "no response from $url/healthz"

status="$(curl -s -o /dev/null -w '%{http_code}' "$url/healthz")"
[[ "$status" == 200 ]] || fail "/healthz returned $status"
echo "ok: /healthz 200"

curl -s -D "$tmp/headers" -c "$tmp/jar" -o "$tmp/home.html" "$url/"
cookie="$(grep -i '^set-cookie: player_id=' "$tmp/headers" || true)"
[[ -n "$cookie" ]] || fail "/ set no player_id cookie"
grep -qi 'httponly' <<<"$cookie" || fail "player_id cookie is not HttpOnly: $cookie"
grep -qi 'secure' <<<"$cookie" || fail "player_id cookie is not Secure: $cookie"
echo "ok: / sets an HttpOnly, Secure player_id cookie"

grep -q 'action="/quizzes/' "$tmp/home.html" || fail "home page lists no quizzes"
echo "ok: home lists $(grep -c 'action="/quizzes/' "$tmp/home.html") quiz(zes)"

# Time to first byte minus connection setup, so it includes one network round trip:
# an upper bound on server time.
for _ in $(seq "$samples"); do
  curl -s -o /dev/null -b "$tmp/jar" -w '%{time_starttransfer} %{time_pretransfer}\n' "$url/"
done | awk '{ printf "%d\n", ($1 - $2) * 1000 }' | sort -n >"$tmp/ms"
p95="$(awk -v n="$samples" 'NR == int(n * 0.95 + 0.999) { print }' "$tmp/ms")"
[[ "$p95" -lt "$limit_ms" ]] || fail "p95 server time ${p95} ms >= ${limit_ms} ms"
echo "ok: p95 server time ${p95} ms over $samples warm requests to /"
