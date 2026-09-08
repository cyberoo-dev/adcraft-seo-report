#!/usr/bin/env python3
"""Quick smoke test for the free SEO data sources used by the Adcraft report skill.

Reads ~/.config/adcraft-seo/keys.env and hits each API once with a test domain.
Usage: python3 check_keys.py [domain]
"""
import json
import os
import sys
import urllib.parse
import urllib.request

DOMAIN = sys.argv[1] if len(sys.argv) > 1 else "adcraftstudio.com.au"
KEYS_PATH = os.path.expanduser("~/.config/adcraft-seo/keys.env")


def load_keys():
    keys = {}
    if not os.path.exists(KEYS_PATH):
        return keys
    for line in open(KEYS_PATH):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        keys[k.strip()] = v.strip().strip('"').strip("'")
    return keys


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 AdcraftSEOReport/1.0"


def call(url, headers=None, data=None, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})}, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def check(name, fn):
    try:
        out = fn()
        print(f"OK   {name}: {out}")
    except Exception as e:  # noqa: BLE001
        body = ""
        if hasattr(e, "read"):
            try:
                body = e.read().decode()[:200]
            except Exception:  # noqa: BLE001
                pass
        print(f"FAIL {name}: {e} {body}")


def relay_call(k, path, payload, timeout=90):
    return call(k["RELAY_URL"].rstrip("/") + path, {"Authorization": f"Bearer {k['RELAY_TOKEN']}", "Content-Type": "application/json"},
                json.dumps(payload).encode(), timeout=timeout)


def main():
    k = load_keys()
    relay = bool(k.get("RELAY_URL") and k.get("RELAY_TOKEN"))
    if relay:
        print(f"Using key relay at {k['RELAY_URL']}")
        try:
            h = call(k["RELAY_URL"].rstrip("/") + "/health")
            print("OK   Relay health:", h.get("vendors"))
        except Exception as e:  # noqa: BLE001
            print("FAIL Relay health:", e)

    def ahrefs():
        key = k.get("AHREFS_API_KEY")
        if not key and relay:
            d = relay_call(k, "/ahrefs", {"target": DOMAIN})
            dr = d.get("domain_rating")
            return f"DR={dr.get('domain_rating') if isinstance(dr, dict) else dr} (via relay)"
        if not key:
            return "skipped (no key)"
        d = call(
            "https://api.ahrefs.com/v3/public/domain-rating-free?target="
            + urllib.parse.quote(DOMAIN),
            {"Authorization": f"Bearer {key}", "Accept": "application/json"},
        )
        return f"DR={d.get('domain_rating')}"

    def opr():
        key = k.get("OPENPAGERANK_API_KEY")
        if not key and relay:
            d = relay_call(k, "/opr", {"domains": [DOMAIN], "include_history": False})
            first = (d.get("results") or [{}])[0]
            return {kk: first.get(kk) for kk in ("domain", "open_page_rank", "rank", "referring_domains")} | {"via": "relay"}
        if not key:
            return "skipped (no key)"
        d = call(
            "https://openpagerank.keywordseverywhere.com/v1/domains/bulk",
            {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json.dumps({"domains": [DOMAIN], "include_history": False}).encode(),
        )
        first = (d.get("results") or d.get("response") or d.get("data") or [d])[0]
        return {kk: first.get(kk) for kk in ("domain", "open_page_rank", "rank", "referring_domains")}

    def serpapi():
        key = k.get("SERPAPI_API_KEY")
        params = {"engine": "google", "q": "digital marketing agency wollongong", "google_domain": "google.com.au",
                  "gl": "au", "hl": "en", "location": "Wollongong, New South Wales, Australia"}
        if not key and relay:
            d = relay_call(k, "/serpapi", {"params": params}, timeout=120)
        elif not key:
            return "skipped (no key)"
        else:
            d = call("https://serpapi.com/search.json?" + urllib.parse.urlencode({**params, "api_key": key}), timeout=60)
        organic = d.get("organic_results", [])
        pos = next((r.get("position") for r in organic if DOMAIN in (r.get("link") or "")), None)
        return f"organic={len(organic)} position_for_test_query={pos} ai_overview={'yes' if d.get('ai_overview') else 'no'}"

    def gemini():
        key = k.get("GEMINI_API_KEY")
        body = {
            "contents": [{"parts": [{"text": "Name three digital marketing agencies in Wollongong, Australia. Answer briefly with website domains."}]}],
            "tools": [{"google_search": {}}],
        }
        if not key and relay:
            d = relay_call(k, "/gemini", {"model": "gemini-2.5-flash", "body": body}, timeout=150)
            text = d["candidates"][0]["content"]["parts"][0].get("text", "")
            return f"ok via relay: {text[:100]!r}"
        if not key:
            return "skipped (no key)"
        d = call(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}",
            {"Content-Type": "application/json"},
            json.dumps(body).encode(),
            timeout=90,
        )
        text = d["candidates"][0]["content"]["parts"][0].get("text", "")
        gm = d["candidates"][0].get("groundingMetadata", {})
        cites = [c.get("web", {}).get("uri") for c in gm.get("groundingChunks", [])]
        return f"mentions_domain={DOMAIN in text or any(DOMAIN in (c or '') for c in cites)} cites={len(cites)} text={text[:120]!r}"

    def reddit():
        key = k.get("SERPAPI_API_KEY")
        params = {"engine": "google", "q": f'site:reddit.com "{DOMAIN}"', "gl": "au", "hl": "en"}
        if not key and relay:
            d = relay_call(k, "/serpapi", {"params": params}, timeout=120)
        elif not key:
            return "skipped (no SerpApi key; Reddit is checked via SerpApi site: search)"
        else:
            d = call("https://serpapi.com/search.json?" + urllib.parse.urlencode({**params, "api_key": key}), timeout=60)
        return f"reddit_results={len(d.get('organic_results', []))} (via SerpApi)"

    def wikipedia():
        brand = DOMAIN.split(".")[0]
        d = call(
            "https://en.wikipedia.org/w/api.php?"
            + urllib.parse.urlencode({"action": "query", "list": "search", "srsearch": f'"{brand}"', "format": "json", "srlimit": 5}),
            {"User-Agent": "adcraft-seo-report/0.1"},
        )
        return f"wikipedia_hits={d.get('query', {}).get('searchinfo', {}).get('totalhits')}"

    print(f"Testing sources for {DOMAIN}\n")
    check("Ahrefs DR", ahrefs)
    check("OpenPageRank", opr)
    check("SerpApi", serpapi)
    check("Gemini grounding", gemini)
    check("Reddit citations", reddit)
    check("Wikipedia citations", wikipedia)


if __name__ == "__main__":
    main()
