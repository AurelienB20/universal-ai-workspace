#!/usr/bin/env bash
# Check a running production stack from the server it runs on.
#   ./smoke-test.sh https://demo.example.com
#   INSECURE=1 ./smoke-test.sh https://localhost    # Caddy's local certificate (CI)
# Reads the API keys from deploy/.env. Calls no model provider: it costs nothing.
set -euo pipefail

cd "$(dirname "$0")"
base=${1:?usage: ./smoke-test.sh <public base URL>}
api=http://127.0.0.1:8000
curl_opts=(--silent --show-error --max-time 20)
[[ "${INSECURE:-0}" == 1 ]] && curl_opts+=(--insecure)

# shellcheck disable=SC1091
set -a; source .env; set +a

failures=0
check() {
  local description=$1 expected=$2 actual=$3
  if [[ "$actual" == "$expected" ]]; then
    echo "ok    $description"
  else
    echo "FAIL  $description: expected '$expected', got '$actual'"
    failures=$((failures + 1))
  fi
}
status() { curl "${curl_opts[@]}" --output /dev/null --write-out '%{http_code}' "$@"; }
header() { curl "${curl_opts[@]}" --head "$2" | tr -d '\r' | grep -i "^$1:" | cut -d' ' -f2- || true; }

# --- Public side, through Caddy ---
check "home page over HTTPS" 200 "$(status "$base/")"
check "HTTP redirects to HTTPS" 308 "$(status "${base/https:/http:}/")"
check "HSTS header" "max-age=31536000" "$(header Strict-Transport-Security "$base/")"
check "Content Security Policy" yes "$( [[ -n "$(header Content-Security-Policy "$base/")" ]] && echo yes || echo no)"
check "no Server header" "" "$(header Server "$base/")"
check "how-it-is-built page" 200 "$(status "$base/architecture")"
check "imports disabled on the demo" '{"importsEnabled":false}' \
  "$(curl "${curl_opts[@]}" "$base/api/config")"
check "repository list" 200 "$(status "$base/api/repositories")"
# A repository outside DEMO_REPOSITORIES: refused by the API before any model call,
# with the same 404 as an unknown repository (the message shows the API answered).
check "streamed answers reach the API" \
  '{"detail":"octo/not-allowed has not been imported yet, or its import is not finished."}' \
  "$(curl "${curl_opts[@]}" -X POST -H 'content-type: application/json' \
      -d '{"repository":"octo/not-allowed","question":"Why?"}' "$base/api/ask/stream")"
check "import route removed" 404 \
  "$(status -X POST -H 'content-type: application/json' -d '{"url":"https://github.com/pallets/flask"}' "$base/api/imports")"

# --- Private side, from the server itself ---
check "API health" 200 "$(status "$api/health")"
check "API database" 200 "$(status "$api/health/ready")"
check "API needs a key" 401 "$(status "$api/repositories")"
check "demo key cannot import" 403 \
  "$(status -X POST -H "X-API-Key: $DEMO_API_KEY" -H 'content-type: application/json' \
      -d '{"url":"https://github.com/pallets/flask"}' "$api/imports")"
check "API bound to localhost only" "127.0.0.1:8000" \
  "$(docker compose -f docker-compose.prod.yml port api 8000)"

if (( failures > 0 )); then
  echo "$failures check(s) failed."
  exit 1
fi
echo "All checks passed."
