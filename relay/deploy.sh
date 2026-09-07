#!/usr/bin/env bash
# Deploy (or redeploy) the key relay to Cloudflare Workers and push the vendor keys as secrets.
# Run on the Mac that holds ~/.config/adcraft-seo/keys.env, after `npx wrangler login` once.
#   ./deploy.sh            deploy + sync secrets (creates RELAY_TOKEN the first time)
#   ./deploy.sh --rotate   deploy + sync secrets + issue a NEW relay token (old one stops working)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
KEYS="$HOME/.config/adcraft-seo/keys.env"
RELAY_FILE="$HOME/.config/adcraft-seo/relay.env"
W="npx --yes wrangler@latest"

val() { grep -E "^$1=" "$KEYS" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'" ; }

echo "==> Deploying worker"
OUT=$($W deploy 2>&1); echo "$OUT" | tail -3
URL=$(echo "$OUT" | grep -oE 'https://[a-z0-9.-]+\.workers\.dev' | head -1 || true)
if [[ -z "$URL" && -f "$RELAY_FILE" ]]; then URL=$(grep -E '^RELAY_URL=' "$RELAY_FILE" | cut -d= -f2-); fi
if [[ -z "$URL" ]]; then echo "Could not determine worker URL; check the deploy output above." >&2; exit 1; fi

echo "==> Syncing vendor keys as secrets"
for k in AHREFS_API_KEY OPENPAGERANK_API_KEY SERPAPI_API_KEY GEMINI_API_KEY GOOGLE_API_KEY; do
  v=$(val "$k")
  if [[ -n "$v" ]]; then printf '%s' "$v" | $W secret put "$k" >/dev/null && echo "   $k set"; fi
done

TOKEN=""
if [[ -f "$RELAY_FILE" && "${1:-}" != "--rotate" ]]; then
  TOKEN=$(grep -E '^RELAY_TOKEN=' "$RELAY_FILE" | cut -d= -f2-)
fi
if [[ -z "$TOKEN" ]]; then
  TOKEN=$(openssl rand -hex 24)
  echo "==> Issued new relay token"
fi
printf '%s' "$TOKEN" | $W secret put RELAY_TOKEN >/dev/null && echo "   RELAY_TOKEN set"
printf 'RELAY_URL=%s\nRELAY_TOKEN=%s\n' "$URL" "$TOKEN" > "$RELAY_FILE"
chmod 600 "$RELAY_FILE"

echo "==> Health: $(curl -s "$URL/health")"
echo
echo "Give the other computer ONLY these two lines (they go in its ~/.config/adcraft-seo/keys.env, vendor keys left blank):"
cat "$RELAY_FILE"
echo
echo "To revoke: ./deploy.sh --rotate  (then update the other computer's keys.env)."
