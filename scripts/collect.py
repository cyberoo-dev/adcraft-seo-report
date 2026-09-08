#!/usr/bin/env python3
"""Collect every measurable signal for an SEO / GEO report into one data.json.

Usage:
  collect.py <url> --out <run_dir> [--keywords "kw1;kw2"] [--prompts "p1;p2"]
             [--brand "Brand Name"] [--location "City, State, Country"]
             [--crawl N] [--skip-external] [--skip-cc] [--skip-psi]

Deterministic, no LLM calls except Gemini (if key present) for prompt visibility.
Writes: <run_dir>/data.json, <run_dir>/shots/{desktop,tablet,mobile}.png
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlparse, quote, urlencode

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    STOPWORDS, UA, domain_of, load_config, load_keys, normalize_url, same_site, write_json,
)

RELAY: dict = {}  # filled from keys.env: RELAY_URL + RELAY_TOKEN (used when vendor keys are absent)


def relay_post(path: str, payload: dict, timeout: int = 90):
    r = SESSION.post(RELAY["url"].rstrip("/") + path, json=payload, headers={"Authorization": f"Bearer {RELAY['token']}"}, timeout=timeout)
    return r


SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept-Language": "en-AU,en;q=0.9"})
# macOS: consulting the system proxy config (SystemConfiguration) makes every later fork()+exec
# child segfault, which kills Playwright and dig. Never let requests touch it.
SESSION.trust_env = False
os.environ.setdefault("no_proxy", "*")
TIMEOUT = 25

SEARCH_BOTS = ["googlebot", "bingbot", "slurp", "duckduckbot", "baiduspider", "yandexbot"]
AI_BOTS = [
    "GPTBot", "ChatGPT-User", "OAI-SearchBot", "Google-Extended", "ClaudeBot", "anthropic-ai",
    "Claude-Web", "PerplexityBot", "Perplexity-User", "CCBot", "Bytespider", "Applebot-Extended",
    "cohere-ai", "meta-externalagent", "Amazonbot", "DuckAssistBot",
]
DEPRECATED_TAGS = ["font", "center", "marquee", "blink", "strike", "big", "tt", "frame", "frameset", "applet", "acronym", "basefont", "dir", "isindex"]


def log(msg: str) -> None:
    print(f"[collect] {msg}", file=sys.stderr, flush=True)


def get(url: str, **kw):
    kw.setdefault("timeout", TIMEOUT)
    kw.setdefault("allow_redirects", True)
    return SESSION.get(url, **kw)


# ----------------------------------------------------------------------------- fetch


def fetch_raw(url: str) -> dict:
    t = time.time()
    r = get(url)
    elapsed = time.time() - t
    return {
        "requested_url": url,
        "final_url": r.url,
        "status": r.status_code,
        "elapsed_s": round(elapsed, 3),
        "headers": {k.lower(): v for k, v in r.headers.items()},
        "html": r.text,
        "bytes": len(r.content),
        "redirects": [h.url for h in r.history],
    }


def https_checks(url: str) -> dict:
    d = domain_of(url)
    out = {"ssl": False, "http_redirects_to_https": False, "www_redirect_ok": None, "errors": []}
    try:
        r = get(f"https://{d}/")
        out["ssl"] = r.status_code < 400
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"https: {e}")
    try:
        r = get(f"http://{d}/")
        out["http_redirects_to_https"] = r.url.startswith("https://")
        out["http_final_url"] = r.url
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"http: {e}")
    try:
        r = get(f"https://www.{d}/")
        out["www_final_url"] = r.url
        out["www_redirect_ok"] = r.status_code < 400
    except Exception as e:  # noqa: BLE001
        out["www_redirect_ok"] = False
        out["errors"].append(f"www: {e}")
    return out


def fetch_robots(url: str) -> dict:
    d = domain_of(url)
    base = urlparse(url)
    robots_url = f"{base.scheme}://{base.netloc}/robots.txt"
    out = {"url": robots_url, "present": False, "text": "", "sitemaps": [], "blocked_search_bots": [],
           "blocked_ai_bots": [], "blocks_all": False}
    try:
        r = get(robots_url)
        if r.status_code == 200 and "<html" not in r.text[:500].lower():
            out["present"] = True
            out["text"] = r.text[:20000]
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)
        return out
    if not out["present"]:
        return out
    # parse groups
    groups: list[tuple[list[str], list[str]]] = []
    agents: list[str] = []
    rules: list[str] = []
    for line in out["text"].splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        k, v = [x.strip() for x in line.split(":", 1)]
        kl = k.lower()
        if kl == "user-agent":
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(v.lower())
        elif kl == "disallow":
            rules.append(v)
        elif kl == "sitemap":
            out["sitemaps"].append(v)
    if agents:
        groups.append((agents, rules))

    def blocked(agent: str) -> bool:
        a = agent.lower()
        matched = None
        for ags, rls in groups:
            if a in ags or any(a.startswith(x) or x in a for x in ags if x != "*"):
                matched = rls
                break
        if matched is None:
            for ags, rls in groups:
                if "*" in ags:
                    matched = rls
        if not matched:
            return False
        return any(r.strip() == "/" for r in matched)

    out["blocked_search_bots"] = [b for b in SEARCH_BOTS if blocked(b)]
    out["blocked_ai_bots"] = [b for b in AI_BOTS if blocked(b)]
    out["blocks_all"] = blocked("*")
    return out


def fetch_sitemap(url: str, robots: dict) -> dict:
    base = urlparse(url)
    candidates = list(dict.fromkeys(robots.get("sitemaps", []) + [
        f"{base.scheme}://{base.netloc}/sitemap.xml",
        f"{base.scheme}://{base.netloc}/sitemap_index.xml",
        f"{base.scheme}://{base.netloc}/sitemap-index.xml",
    ]))
    out = {"present": False, "url": None, "url_count": 0, "child_sitemaps": 0, "urls": []}
    for c in candidates:
        try:
            r = get(c)
        except Exception:  # noqa: BLE001
            continue
        if r.status_code != 200 or "<urlset" not in r.text and "<sitemapindex" not in r.text:
            continue
        out["present"] = True
        out["url"] = c
        soup = BeautifulSoup(r.text, "xml")
        if soup.find("sitemapindex"):
            children = [s.get_text(strip=True) for s in soup.select("sitemap > loc")]
            out["child_sitemaps"] = len(children)
            for ch in children[:5]:
                try:
                    rr = get(ch)
                    if rr.status_code == 200:
                        cs = BeautifulSoup(rr.text, "xml")
                        out["urls"] += [u.get_text(strip=True) for u in cs.select("url > loc")]
                except Exception:  # noqa: BLE001
                    pass
        else:
            out["urls"] = [u.get_text(strip=True) for u in soup.select("url > loc")]
        out["url_count"] = len(out["urls"])
        out["urls"] = out["urls"][:500]
        break
    return out


def fetch_llms(url: str) -> dict:
    base = urlparse(url)
    u = f"{base.scheme}://{base.netloc}/llms.txt"
    try:
        r = get(u)
        ok = r.status_code == 200 and "text" in r.headers.get("content-type", "") and "<html" not in r.text[:300].lower()
        return {"present": bool(ok), "url": u, "size": len(r.text) if ok else 0}
    except Exception as e:  # noqa: BLE001
        return {"present": False, "url": u, "error": str(e)}


def favicon_check(url: str, soup: BeautifulSoup) -> dict:
    icons = [l.get("href") for l in soup.find_all("link", rel=True) if any("icon" in r.lower() for r in (l.get("rel") or []))]
    if icons:
        return {"present": True, "href": urljoin(url, icons[0])}
    base = urlparse(url)
    try:
        r = get(f"{base.scheme}://{base.netloc}/favicon.ico")
        if r.status_code == 200 and len(r.content) > 0:
            return {"present": True, "href": f"{base.scheme}://{base.netloc}/favicon.ico"}
    except Exception:  # noqa: BLE001
        pass
    return {"present": False}


def dns_checks(domain: str) -> dict:
    out = {"dmarc": None, "spf": None, "ns": [], "a": []}
    import shutil
    import socket

    def dig(qtype: str, name: str) -> list[str]:
        try:
            if shutil.which("dig"):
                r = subprocess.run(["dig", "+short", qtype, name], capture_output=True, text=True, timeout=15)
                return [x.strip().strip('"').replace('" "', "") for x in r.stdout.splitlines() if x.strip()]
            if shutil.which("nslookup"):  # Windows fallback
                r = subprocess.run(["nslookup", f"-type={qtype}", name], capture_output=True, text=True, timeout=15)
                vals = []
                for line in r.stdout.splitlines():
                    s = line.strip()
                    if qtype == "TXT" and '"' in s:
                        vals.append(s.split('"', 1)[1].rsplit('"', 1)[0].replace('" "', ""))
                    elif qtype == "NS" and "nameserver =" in s:
                        vals.append(s.split("=", 1)[1].strip())
                    elif qtype == "A" and s.startswith("Address") and "#" not in s and name not in s:
                        vals.append(s.split(":", 1)[1].strip())
                return vals
            if qtype == "A":
                return [socket.gethostbyname(name)]
        except Exception as e:  # noqa: BLE001
            out.setdefault("errors", []).append(f"dns {qtype} {name}: {e}")
        return []

    for t in dig("TXT", f"_dmarc.{domain}"):
        if t.lower().startswith("v=dmarc1"):
            out["dmarc"] = t
    for t in dig("TXT", domain):
        if t.lower().startswith("v=spf1"):
            out["spf"] = t
    out["ns"] = dig("NS", domain)
    out["a"] = [x for x in dig("A", domain) if re.match(r"^\d+\.\d+\.\d+\.\d+$", x)]
    return out


# ----------------------------------------------------------------------------- browser


def browser_pass(url: str, shots_dir: Path) -> dict:
    """Load the page in Chromium, capture resources, timings, errors, rendered HTML, screenshots."""
    from playwright.sync_api import sync_playwright

    out: dict = {"resources": [], "js_errors": [], "console_errors": [], "timing": {}, "rendered_html": "",
                 "rendered_text": "", "protocol": None, "screenshots": {}, "error": None}
    shots_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2, user_agent=UA)
        page = ctx.new_page()
        cdp = ctx.new_cdp_session(page)
        cdp.send("Network.enable")
        meta: dict[str, dict] = {}
        wire: dict[str, int] = {}

        def on_resp(ev):
            r = ev.get("response", {})
            meta[ev["requestId"]] = {
                "url": r.get("url"), "type": ev.get("type"), "mime": r.get("mimeType"),
                "status": r.get("status"), "protocol": r.get("protocol"),
                "encoding": {k.lower(): v for k, v in (r.get("headers") or {}).items()}.get("content-encoding"),
            }

        def on_done(ev):
            wire[ev["requestId"]] = int(ev.get("encodedDataLength") or 0)

        cdp.on("Network.responseReceived", on_resp)
        cdp.on("Network.loadingFinished", on_done)
        page.on("pageerror", lambda e: out["js_errors"].append(str(e)[:300]))
        page.on("console", lambda m: out["console_errors"].append(m.text[:300]) if m.type == "error" else None)
        bodies: dict[str, int] = {}
        page.on("response", lambda r: bodies.__setitem__(r.url, _safe_len(r)))
        try:
            page.goto(url, wait_until="load", timeout=60000)
            page.wait_for_timeout(3000)
            out["timing"] = page.evaluate(
                """() => { const n = performance.getEntriesByType('navigation')[0]; if(!n) return {};
                return { responseStart: n.responseStart, domContentLoaded: n.domContentLoadedEventEnd,
                         load: n.loadEventEnd, transferSize: n.transferSize, protocol: n.nextHopProtocol }; }"""
            )
            out["rendered_html"] = page.content()
            out["rendered_text"] = page.evaluate("() => document.body ? document.body.innerText : ''")
            out["protocol"] = out["timing"].get("protocol")
            page.screenshot(path=str(shots_dir / "desktop.png"))
            out["screenshots"]["desktop"] = str(shots_dir / "desktop.png")
        except Exception as e:  # noqa: BLE001
            out["error"] = str(e)[:300]
        page.wait_for_timeout(500)
        for rid, m in meta.items():
            m = dict(m)
            m["wire_bytes"] = wire.get(rid, 0)
            m["raw_bytes"] = bodies.get(m["url"], 0) or m["wire_bytes"]
            out["resources"].append(m)
        ctx.close()
        for name, vp, mobile in (("tablet", (768, 1024), True), ("mobile", (390, 844), True)):
            try:
                c = browser.new_context(viewport={"width": vp[0], "height": vp[1]}, device_scale_factor=2,
                                        is_mobile=mobile, has_touch=mobile, user_agent=UA)
                pg = c.new_page()
                pg.goto(url, wait_until="load", timeout=60000)
                pg.wait_for_timeout(2500)
                pg.screenshot(path=str(shots_dir / f"{name}.png"))
                out["screenshots"][name] = str(shots_dir / f"{name}.png")
                c.close()
            except Exception as e:  # noqa: BLE001
                out.setdefault("screenshot_errors", []).append(f"{name}: {str(e)[:200]}")
        browser.close()
    return out


def _safe_len(resp) -> int:
    try:
        if resp.status in (301, 302, 303, 307, 308, 204):
            return 0
        return len(resp.body())
    except Exception:  # noqa: BLE001
        return 0


def summarize_resources(resources: list[dict]) -> dict:
    cat = {"html": 0, "css": 0, "js": 0, "images": 0, "other": 0}
    raw = dict(cat)
    wire = dict(cat)
    for r in resources:
        t = (r.get("type") or "").lower()
        mime = (r.get("mime") or "").lower()
        if t == "document" or "text/html" in mime:
            k = "html"
        elif t == "stylesheet" or "css" in mime:
            k = "css"
        elif t == "script" or "javascript" in mime:
            k = "js"
        elif t == "image" or mime.startswith("image/"):
            k = "images"
        else:
            k = "other"
        cat[k] += 1
        raw[k] += r.get("raw_bytes") or 0
        wire[k] += r.get("wire_bytes") or 0
    total_raw = sum(raw.values())
    total_wire = sum(wire.values())
    comp = {k: (round(100 * (1 - wire[k] / raw[k])) if raw[k] > 0 and wire[k] <= raw[k] else 0) for k in cat}
    protocols = Counter((r.get("protocol") or "?") for r in resources)
    return {
        "counts": cat, "total_objects": len(resources),
        "raw_bytes": raw, "wire_bytes": wire, "total_raw": total_raw, "total_wire": total_wire,
        "compression_pct": comp,
        "total_compression_pct": round(100 * (1 - total_wire / total_raw)) if total_raw and total_wire <= total_raw else 0,
        "protocols": dict(protocols),
    }


# ----------------------------------------------------------------------------- parse


def visible_text(soup: BeautifulSoup) -> str:
    s = BeautifulSoup(str(soup), "lxml")
    for t in s(["script", "style", "noscript", "template", "svg"]):
        t.decompose()
    return re.sub(r"\s+", " ", s.get_text(" ", strip=True))


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z'\-]{1,}", text.lower())]


def network_signals(resources: list[dict]) -> dict:
    urls = [r.get("url") or "" for r in resources]
    joined = "\n".join(urls)
    out = {"facebook_pixel": None, "ga_ids": [], "gtm_ids": [], "tech": []}
    m = re.search(r"facebook\.com/tr/?\?[^\n]*?id=(\d+)", joined)
    if m:
        out["facebook_pixel"] = m.group(1)
    out["ga_ids"] = sorted(set(re.findall(r"(?:tid=|id=)(G-[A-Z0-9]{6,}|UA-\d+-\d+)", joined)))
    out["gtm_ids"] = sorted(set(re.findall(r"id=(GTM-[A-Z0-9]+)", joined)))
    for name, pat in (("Google Analytics", r"google-analytics\.com|/g/collect|gtag/js"), ("Google Tag Manager", r"googletagmanager\.com/gtm"),
                      ("Facebook Pixel", r"facebook\.com/tr|connect\.facebook\.net"), ("LinkedIn Insight Tag", r"snap\.licdn\.com|px\.ads\.linkedin"),
                      ("Hotjar", r"hotjar\.com"), ("Microsoft Clarity", r"clarity\.ms"), ("HubSpot", r"hs-scripts|hubspot"),
                      ("Google Font API", r"fonts\.g(oogleapis|static)\.com"), ("Google Hosted Libraries", r"ajax\.googleapis\.com"),
                      ("Cloudflare", r"cdn-cgi/|cloudflareinsights"), ("Birdeye", r"birdeye\.com"), ("MailChimp", r"chimpstatic|list-manage"),
                      ("Klaviyo", r"klaviyo"), ("TikTok Pixel", r"analytics\.tiktok\.com"), ("Pinterest Tag", r"ct\.pinterest\.com"),
                      ("Google Ads", r"googleads\.g\.doubleclick|googleadservices"), ("YouTube", r"youtube\.com|ytimg"), ("Vimeo", r"vimeo"),
                      ("Unpkg", r"unpkg\.com"), ("jsDelivr", r"jsdelivr"), ("Cloudinary", r"cloudinary"), ("Wistia", r"wistia")):
        if re.search(pat, joined, re.I):
            out["tech"].append(name)
    return out


def parse_page(url: str, html: str, rendered_html: str, rendered_text: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    head = soup.head or soup
    title = (soup.title.get_text(strip=True) if soup.title else "") or ""
    md = head.find("meta", attrs={"name": re.compile("^description$", re.I)})
    meta_desc = (md.get("content") or "").strip() if md else ""
    canon = head.find("link", rel=lambda r: r and "canonical" in [x.lower() for x in (r if isinstance(r, list) else [r])])
    robots_meta = [m.get("content", "") for m in head.find_all("meta", attrs={"name": re.compile("^robots$|googlebot", re.I)})]
    noindex_tag = any("noindex" in (c or "").lower() for c in robots_meta)
    lang = (soup.html.get("lang") if soup.html else None) or ""
    hreflangs = [{"lang": l.get("hreflang"), "href": l.get("href")} for l in head.find_all("link", attrs={"hreflang": True})]
    viewport = head.find("meta", attrs={"name": re.compile("^viewport$", re.I)})
    headings = {f"h{i}": [h.get_text(" ", strip=True)[:120] for h in soup.find_all(f"h{i}")] for i in range(1, 7)}
    imgs = soup.find_all("img")
    missing_alt = []
    for im in imgs:
        src = im.get("src") or im.get("data-src") or ""
        if src.startswith("data:"):
            continue
        alt = im.get("alt")
        if alt is None or not str(alt).strip():
            missing_alt.append(urljoin(url, src))
    # links
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("#", "mailto:", "tel:", "javascript:")) or not href:
            continue
        full = urljoin(url, href)
        rel = " ".join(a.get("rel") or []).lower()
        links.append({"url": full, "internal": same_site(full, url), "nofollow": "nofollow" in rel,
                      "text": a.get_text(" ", strip=True)[:80]})
    all_links = links
    uniq = {}
    for l in links:
        uniq.setdefault(l["url"], l)
    links = list(uniq.values())
    internal = [l for l in links if l["internal"]]
    external = [l for l in links if not l["internal"]]
    unfriendly = []
    for l in internal:
        p = urlparse(l["url"])
        reasons = []
        if len(l["url"]) > 100:
            reasons.append("long")
        if p.query:
            reasons.append("parameters")
        if "_" in p.path:
            reasons.append("underscores")
        if re.search(r"[A-Z]", p.path):
            reasons.append("uppercase")
        if re.search(r"\.(php|asp|aspx|jsp|cgi|html?)$", p.path, re.I):
            reasons.append("file extension")
        if re.search(r"%[0-9A-F]{2}", p.path):
            reasons.append("encoded characters")
        if p.path.count("/") > 4:
            reasons.append("deep folders")
        if reasons:
            unfriendly.append({"url": l["url"], "reasons": reasons})
    # scripts / tech
    scripts_src = [s.get("src") for s in soup.find_all("script", src=True)]
    inline_js = " ".join(s.get_text() for s in soup.find_all("script") if not s.get("src"))
    all_html_l = html.lower()
    analytics = []
    if re.search(r"gtag\(|googletagmanager\.com/gtag|google-analytics\.com|G-[A-Z0-9]{6,}|UA-\d+-\d+", html):
        analytics.append("Google Analytics")
    if "googletagmanager.com/gtm.js" in html or "GTM-" in html:
        analytics.append("Google Tag Manager")
    for name, pat in (("Matomo", r"matomo|piwik"), ("Plausible", r"plausible\.io"), ("Fathom", r"usefathom"),
                      ("Hotjar", r"hotjar"), ("Microsoft Clarity", r"clarity\.ms"), ("Segment", r"segment\.com/analytics")):
        if re.search(pat, all_html_l):
            analytics.append(name)
    fb_pixel = re.search(r"fbq\(\s*['\"]init['\"]\s*,\s*['\"](\d+)['\"]", inline_js)
    # schema
    schema_blocks, schema_types = [], []
    for s in soup.find_all("script", type=re.compile("ld\\+json", re.I)):
        try:
            data = json.loads(s.get_text() or "{}")
        except Exception:  # noqa: BLE001
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if isinstance(it, dict) and "@graph" in it:
                items.extend(x for x in it["@graph"] if isinstance(x, dict))
        for it in items:
            if isinstance(it, dict):
                schema_blocks.append(it)
                t = it.get("@type")
                schema_types += t if isinstance(t, list) else [t] if t else []
    nested_types: list[str] = []

    def _walk(o):
        if isinstance(o, dict):
            t = o.get("@type")
            if t:
                nested_types.extend(t if isinstance(t, list) else [t])
            for v in o.values():
                _walk(v)
        elif isinstance(o, list):
            for v in o:
                _walk(v)

    _walk(schema_blocks)
    nested_types = [t for t in dict.fromkeys(nested_types) if isinstance(t, str)]
    microdata = bool(soup.find(attrs={"itemtype": True}))
    schema_types = [t for t in dict.fromkeys(schema_types) if t]
    identity_types = [t for t in schema_types if t in ("Organization", "Person", "LocalBusiness", "ProfessionalService", "Corporation") or "Business" in t or "Service" in t or "Store" in t]
    local_types = [t for t in schema_types if t in ("LocalBusiness", "ProfessionalService") or "Business" in t or t in ("Store", "Restaurant", "Dentist", "Physician", "Plumber", "Electrician", "HomeAndConstructionBusiness", "LegalService", "MedicalBusiness", "AutoRepair", "RealEstateAgent", "FinancialService", "HealthAndBeautyBusiness")]
    local_block = next((b for b in schema_blocks if (b.get("@type") in local_types) or (isinstance(b.get("@type"), list) and set(b["@type"]) & set(local_types))), None)
    if not local_block:
        local_block = next((b for b in schema_blocks if isinstance(b.get("address"), dict) and (b.get("@type") in ("Organization", "Corporation") or (isinstance(b.get("@type"), list) and "Organization" in b["@type"]))), None)
        if local_block:
            local_types = list(local_block["@type"] if isinstance(local_block["@type"], list) else [local_block["@type"]])
    # og / twitter
    og = {m.get("property"): m.get("content") for m in head.find_all("meta", property=re.compile("^og:", re.I))}
    tw = {m.get("name"): m.get("content") for m in head.find_all("meta", attrs={"name": re.compile("^twitter:", re.I)})}
    # social links
    social = {}
    for l in external:
        u = l["url"].lower()
        for key, pat in (("facebook", r"facebook\.com/(?!sharer|share)"), ("x", r"(twitter\.com|x\.com)/(?!intent|share)"),
                         ("instagram", r"instagram\.com/"), ("linkedin", r"linkedin\.com/(company|in)/"),
                         ("youtube", r"(youtube\.com/(channel|c|user|@)|youtu\.be)"), ("tiktok", r"tiktok\.com/@"),
                         ("pinterest", r"pinterest\.com/")):
            if re.search(pat, u) and key not in social:
                social[key] = l["url"]
    # misc
    iframes = [f.get("src") for f in soup.find_all("iframe")]
    flash = bool(soup.find(["embed", "object"], attrs={"type": re.compile("shockwave|flash", re.I)}) or ".swf" in all_html_l)
    emails = sorted(set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", visible_text(soup))) | set(re.findall(r"mailto:([^\"'?]+)", html)))
    inline_styles = [t.get("style")[:120] for t in soup.find_all(style=True)]
    deprecated = sorted({t.name for t in soup.find_all(DEPRECATED_TAGS)})
    amp = {"html_amp_attr": bool(soup.find("html", attrs={"amp": True}) or soup.find("html", attrs={"⚡": True})),
           "amp_runtime": "cdn.ampproject.org/v0.js" in html, "amp_boilerplate": "amp-boilerplate" in html,
           "amp_link": bool(head.find("link", rel="amphtml"))}
    # text & keywords
    raw_text = visible_text(soup)
    text_for_count = rendered_text if rendered_text and len(rendered_text) > len(raw_text) * 0.5 else raw_text
    wc = len(words(text_for_count))
    ws = [w for w in words(text_for_count) if w not in STOPWORDS and len(w) > 2]
    single = Counter(ws).most_common(12)
    toks = words(text_for_count)
    bigrams = Counter(" ".join(toks[i:i + 2]) for i in range(len(toks) - 1)
                      if toks[i] not in STOPWORDS and toks[i + 1] not in STOPWORDS).most_common(10)
    hd_text = " ".join(sum(headings.values(), [])).lower()

    def flags(term: str) -> dict:
        return {"title": term in title.lower(), "meta": term in meta_desc.lower(), "headings": term in hd_text}

    keywords = [{"keyword": k, "frequency": c, **flags(k)} for k, c in single]
    phrases = [{"keyword": k, "frequency": c, **flags(k)} for k, c in bigrams if c > 1]
    # rendering percentage: share of rendered words not present in raw HTML text
    raw_set = set(words(raw_text))
    rw = words(rendered_text) if rendered_text else []
    new_words = [w for w in rw if w not in raw_set]
    text_pct = round(100 * len(new_words) / len(rw)) if rw else 0
    size_pct = round(100 * (len(rendered_html) - len(html)) / len(rendered_html)) if rendered_html and len(rendered_html) > len(html) else 0
    render_pct = max(text_pct, size_pct)
    # technologies
    tech = detect_tech(html, scripts_src)
    # question headings / FAQ signals (AEO)
    all_heads = sum(headings.values(), [])
    question_heads = [h for h in all_heads if h.strip().endswith("?") or re.match(r"^(what|how|why|when|where|who|which|can|do|does|is|are|should)\b", h.strip(), re.I)]
    faq_schema = any(t in ("FAQPage", "QAPage", "Question") for t in schema_types)
    dates = re.findall(r"\b(20[12]\d)\b", raw_text)
    year_counts = Counter(dates)
    return {
        "title": title, "title_length": len(title),
        "meta_description": meta_desc, "meta_description_length": len(meta_desc),
        "canonical": canon.get("href") if canon else None,
        "robots_meta": robots_meta, "noindex_tag": noindex_tag,
        "lang": lang, "hreflang": hreflangs, "viewport": viewport.get("content") if viewport else None,
        "headings": headings, "heading_counts": {k: len(v) for k, v in headings.items()},
        "images_total": len([i for i in imgs if not (i.get("src") or "").startswith("data:")]),
        "images_missing_alt": missing_alt,
        "links": {"total": len(all_links), "unique": len(links), "internal": len([l for l in all_links if l["internal"]]),
                  "external_follow": len([l for l in all_links if not l["internal"] and not l["nofollow"]]),
                  "external_nofollow": len([l for l in all_links if not l["internal"] and l["nofollow"]]),
                  "list": [{"url": l["url"], "type": "Internal" if l["internal"] else "External", "follow": "Nofollow" if l["nofollow"] else "Follow"} for l in links[:120]]},
        "unfriendly_urls": unfriendly[:20],
        "analytics": sorted(set(analytics)), "facebook_pixel": fb_pixel.group(1) if fb_pixel else None,
        "schema_types": schema_types, "schema_all_types": nested_types, "schema_jsonld": bool(schema_blocks), "schema_microdata": microdata,
        "identity_schema": identity_types, "local_schema": local_types, "local_schema_block": local_block,
        "og": og, "twitter": tw, "social": social,
        "iframes": iframes, "flash": flash, "emails": emails,
        "inline_styles_count": len(inline_styles), "inline_styles_sample": inline_styles[:15],
        "deprecated_tags": deprecated, "amp": amp,
        "word_count": wc, "keywords": keywords, "phrases": phrases,
        "render_pct": render_pct, "tech": tech,
        "question_headings": question_heads[:20], "faq_schema": faq_schema,
        "year_mentions": dict(year_counts.most_common(4)),
        "raw_text_excerpt": raw_text[:6000], "rendered_text_excerpt": (rendered_text or "")[:6000],
    }


def detect_tech(html: str, scripts: list[str]) -> list[str]:
    h = html.lower()
    s = " ".join(x or "" for x in scripts).lower()
    found = []
    rules = [
        ("WordPress", r"wp-content|wp-includes"), ("WooCommerce", r"woocommerce"), ("Elementor", r"elementor"),
        ("Webflow", r"webflow|website-files\.com"), ("Shopify", r"cdn\.shopify\.com|shopify"), ("Wix", r"wixstatic|wix\.com"),
        ("Squarespace", r"squarespace"), ("Next.js", r"_next/static|__next"), ("React", r"react(-dom)?(\.production)?\.min\.js|data-reactroot"),
        ("Vue.js", r"vue(\.min)?\.js|data-v-"), ("Nuxt", r"__nuxt"), ("jQuery", r"jquery"), ("Bootstrap", r"bootstrap(\.min)?\.(css|js)"),
        ("Tailwind CSS", r"tailwind"), ("Google Tag Manager", r"googletagmanager\.com"), ("Google Analytics", r"gtag\(|google-analytics|googletagmanager\.com/gtag"),
        ("Google Font API", r"fonts\.googleapis\.com"), ("Facebook Pixel", r"connect\.facebook\.net|fbq\("), ("LinkedIn Insight Tag", r"snap\.licdn\.com|_linkedin_partner_id"),
        ("Hotjar", r"hotjar"), ("Microsoft Clarity", r"clarity\.ms"), ("HubSpot", r"hs-scripts|hubspot"), ("MailChimp", r"mailchimp|list-manage\.com|chimpstatic"),
        ("Klaviyo", r"klaviyo"), ("Birdeye", r"birdeye"), ("Lenis", r"lenis"), ("GSAP", r"gsap"), ("Cloudflare", r"cloudflare|cdn-cgi"),
        ("Unpkg", r"unpkg\.com"), ("jsDelivr", r"jsdelivr"), ("Font Awesome", r"font-?awesome"), ("Stripe", r"js\.stripe\.com"),
        ("reCAPTCHA", r"recaptcha"), ("YouTube embed", r"youtube\.com/embed"), ("Vimeo", r"player\.vimeo"), ("Intercom", r"intercom"),
        ("Tawk.to", r"tawk\.to"), ("Calendly", r"calendly"), ("Typeform", r"typeform"), ("PHP", r"\.php"),
    ]
    for name, pat in rules:
        if re.search(pat, h) or re.search(pat, s):
            found.append(name)
    return found


# ----------------------------------------------------------------------------- external


def ahrefs_dr(domain: str, key: str | None) -> dict:
    if not key and not RELAY:
        return {"available": False, "reason": "no AHREFS_API_KEY"}
    try:
        if key:
            r = get(f"https://api.ahrefs.com/v3/public/domain-rating-free?target={quote(domain)}",
                    headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
        else:
            r = relay_post("/ahrefs", {"target": domain})
        if r.status_code != 200:
            return {"available": False, "reason": f"HTTP {r.status_code}: {r.text[:120]}"}
        d = r.json()
        dr = d.get("domain_rating")
        if isinstance(dr, dict):
            dr = dr.get("domain_rating")
        return {"available": True, "domain_rating": dr, "attribution": "Domain Rating by Ahrefs"}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "reason": str(e)}


def openpagerank(domains: list[str], key: str | None) -> dict:
    if not key and not RELAY:
        return {"available": False, "reason": "no OPENPAGERANK_API_KEY"}
    try:
        if key:
            r = SESSION.post("https://openpagerank.keywordseverywhere.com/v1/domains/bulk",
                             headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                             json={"domains": domains[:100], "include_history": True}, timeout=TIMEOUT)
        else:
            r = relay_post("/opr", {"domains": domains[:100], "include_history": True})
        if r.status_code != 200:
            return {"available": False, "reason": f"HTTP {r.status_code}: {r.text[:160]}"}
        d = r.json()
        rows = d.get("response") or d.get("data") or d.get("domains") or d.get("results") or []
        if isinstance(rows, dict):
            rows = list(rows.values())
        return {"available": True, "rows": rows, "raw_keys": list(d.keys())}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "reason": str(e)}


def claude_seo_root() -> Path | None:
    """Locate the claude-seo scripts: CLAUDE_SEO_ROOT (git clone) or the newest plugin cache version."""
    env_root = os.environ.get("CLAUDE_SEO_ROOT")
    if env_root and (Path(env_root) / "scripts").is_dir():
        return Path(env_root)
    cache = Path(os.path.expanduser("~/.claude/plugins/cache/agricidaniel-claude-seo/claude-seo"))
    vers = sorted([p for p in cache.glob("*") if (p / "scripts").is_dir()], key=lambda p: [int(x) if x.isdigit() else x for x in re.split(r"[.]", p.name)])
    if vers:
        return vers[-1]
    local = Path(os.path.expanduser("~/Library/Application Support/claude-seo/src")) if sys.platform == "darwin" else Path(os.environ.get("LOCALAPPDATA", "")) / "claude-seo" / "src"
    return local if (local / "scripts").is_dir() else None


def commoncrawl(domain: str) -> dict:
    root = claude_seo_root()
    if not root:
        return {"available": False, "reason": "claude-seo engine not installed"}
    env = dict(os.environ)
    try:
        r = subprocess.run([sys.executable, str(root / "scripts" / "commoncrawl_graph.py"), domain, "--json"],
                           capture_output=True, text=True, timeout=420, env=env)
        m = re.search(r"\{.*\}", r.stdout, re.S)
        if not m:
            return {"available": False, "reason": (r.stderr or r.stdout)[-300:]}
        d = json.loads(m.group(0))
        if d.get("status") != "success":
            return {"available": False, "reason": str(d.get("error"))[:200]}
        return {"available": True, **d.get("data", {}), "release": d.get("metadata", {}).get("release")}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "reason": str(e)[:200]}


def pagespeed(url: str, key: str | None, strategy: str) -> dict:
    params = {"url": url, "strategy": strategy, "category": ["performance", "seo", "accessibility", "best-practices"]}
    try:
        if not key and RELAY:
            r = relay_post("/psi", {"params": params}, timeout=150)
        else:
            if key:
                params["key"] = key
            r = get("https://www.googleapis.com/pagespeedonline/v5/runPagespeed", params=params, timeout=120)
        if r.status_code != 200:
            return {"available": False, "reason": f"HTTP {r.status_code}: {r.text[:160]}"}
        d = r.json()
        lh = d.get("lighthouseResult", {})
        cats = {k: round((v.get("score") or 0) * 100) for k, v in lh.get("categories", {}).items()}
        audits = lh.get("audits", {})

        def av(k):
            a = audits.get(k, {})
            return {"display": a.get("displayValue"), "numeric": a.get("numericValue"), "score": a.get("score")}

        lab = {k: av(k) for k in ("largest-contentful-paint", "first-contentful-paint", "cumulative-layout-shift",
                                  "total-blocking-time", "speed-index", "interactive", "server-response-time")}
        le = d.get("loadingExperience", {})
        field = {k: {"percentile": v.get("percentile"), "category": v.get("category")} for k, v in le.get("metrics", {}).items()}
        opps = [{"title": a.get("title"), "savings": a.get("displayValue")} for a in audits.values()
                if a.get("details", {}).get("type") == "opportunity" and (a.get("score") or 1) < 0.9][:8]
        return {"available": True, "scores": cats, "lab": lab, "field": field,
                "field_category": le.get("overall_category"), "has_field_data": bool(field), "opportunities": opps}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "reason": str(e)[:200]}


def serpapi_search(params: dict, key: str | None) -> dict:
    if key:
        r = get("https://serpapi.com/search.json", params={**params, "api_key": key}, timeout=90)
    elif RELAY:
        r = relay_post("/serpapi", {"params": params}, timeout=120)
    else:
        raise RuntimeError("no SERPAPI_API_KEY and no relay")
    if r.status_code != 200:
        raise RuntimeError(f"SerpApi HTTP {r.status_code}: {r.text[:160]}")
    return r.json()


def serp_ok(key: str | None) -> bool:
    return bool(key or RELAY)


def serpapi_resolve_location(location: str, key: str) -> str:
    """Map a human-readable location ("Wollongong, NSW, Australia") to SerpApi's canonical name
    ("Wollongong,New South Wales,Australia"). The locations endpoint is free and does not count as a search."""
    if not location:
        return location
    try:
        q = location.split(",")[0].strip()
        r = get("https://serpapi.com/locations.json", params={"q": q, "limit": 10}, timeout=30)
        cands = r.json() if r.status_code == 200 else []
    except Exception:  # noqa: BLE001
        return location
    if not cands:
        return location
    tail = [t.strip().lower() for t in location.split(",")[1:]]
    # Prefer canonical names that also contain the other parts the user gave (state / country).
    for c in cands:
        canon = (c.get("canonical_name") or "")
        low = canon.lower()
        if canon and all(t in low for t in tail if t and t not in ("nsw", "vic", "qld", "wa", "sa", "tas", "act", "nt")):
            return canon
    return cands[0].get("canonical_name") or location


def serp_rankings(domain: str, keywords: list[str], key: str | None, cfg: dict, location: str) -> dict:
    if not serp_ok(key):
        return {"available": False, "reason": "no SERPAPI_API_KEY"}
    if not keywords:
        return {"available": False, "reason": "no keywords supplied"}
    location = serpapi_resolve_location(location, key)
    rows, errors = [], []
    depth = int(cfg.get("serp_pages", 2))  # Google returns 10 results per call; each page costs one SerpApi search
    for kw in keywords:
        organic, d, pos = [], {}, None
        for page in range(depth):
            try:
                dd = serpapi_search({"engine": "google", "q": kw, "google_domain": cfg.get("google_domain", "google.com.au"),
                                     "gl": cfg.get("gl", "au"), "hl": cfg.get("hl", "en"), "location": location, "start": page * 10}, key)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{kw} p{page + 1}: {e}")
                break
            if page == 0:
                d = dd
            batch = dd.get("organic_results", []) or []
            for i, r in enumerate(batch):
                r["position"] = page * 10 + i + 1
            organic += batch
            pos = next((r.get("position") for r in organic if domain in (r.get("link") or "").lower()), None)
            if pos is not None or not batch:
                break
        if not d:
            continue
        top = [{"position": r.get("position"), "title": (r.get("title") or "")[:80], "link": r.get("link")} for r in organic[:5]]
        aio = d.get("ai_overview") or {}
        aio_present = bool(aio)
        aio_refs = [x.get("link") for x in (aio.get("references") or aio.get("sources") or []) if isinstance(x, dict)]
        aio_cited = any(domain in (l or "").lower() for l in aio_refs)
        aio_text = " ".join(b.get("snippet", "") for b in (aio.get("text_blocks") or []) if isinstance(b, dict))
        local = d.get("local_results", {})
        places = local.get("places", []) if isinstance(local, dict) else (local or [])
        local_pos = next((i + 1 for i, p in enumerate(places) if domain in (p.get("website") or p.get("links", {}).get("website") or "").lower()), None)
        rows.append({"keyword": kw, "position": pos, "checked_to": len(organic), "top": top, "ai_overview": aio_present,
                     "ai_overview_cited": aio_cited, "ai_overview_refs": aio_refs[:10], "ai_overview_text": aio_text[:400],
                     "local_pack_position": local_pos, "local_pack_names": [p.get("title") for p in places[:3]],
                     "paa": [q.get("question") for q in (d.get("related_questions") or [])[:4]]})
    return {"available": True, "rows": rows, "errors": errors, "location": location, "depth": depth * 10}


def serp_citations(domain: str, brand: str, key: str | None, cfg: dict) -> dict:
    out = {"reddit": {"available": False}, "youtube": {"available": False}}
    if not serp_ok(key):
        return out
    for name, q in (("reddit", f'site:reddit.com "{brand}" OR "{domain}"'), ("youtube", f'site:youtube.com "{brand}" OR "{domain}"')):
        try:
            d = serpapi_search({"engine": "google", "q": q, "google_domain": cfg.get("google_domain", "google.com.au"),
                                "gl": cfg.get("gl", "au"), "hl": cfg.get("hl", "en"), "num": 10}, key)
            res = [{"title": (r.get("title") or "")[:100], "link": r.get("link"), "snippet": (r.get("snippet") or "")[:200]}
                   for r in d.get("organic_results", []) or []]
            out[name] = {"available": True, "count": len(res), "results": res[:5]}
        except Exception as e:  # noqa: BLE001
            out[name] = {"available": False, "reason": str(e)[:160]}
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def serp_gbp_full(brand: str, location: str, domain: str, key: str | None, cfg: dict, want_reviews: bool = True) -> dict:
    """Google Maps listing + place details + newest reviews. Costs 3 SerpApi searches (1 without reviews/details)."""
    base = serp_gbp(brand, location, domain, key, cfg)
    if not base.get("available") or not base.get("found") or base.get("unverified"):
        return base
    out = dict(base)
    try:
        if base.get("data_id") or base.get("place_id"):
            params = {"engine": "google_maps", "hl": cfg.get("hl", "en"), "gl": cfg.get("gl", "au")}
            if base.get("place_id"):
                params["place_id"] = base["place_id"]
            else:
                params["data_id"] = base["data_id"]
            d = serpapi_search(params, key)
            pr = d.get("place_results") or {}
            out["details"] = {
                "description": pr.get("description"), "type": pr.get("type"), "types": pr.get("types") or [],
                "hours": pr.get("hours") or pr.get("operating_hours"), "open_state": pr.get("open_state"),
                "images_count": len(pr.get("images") or []), "posts": [{"date": p.get("date"), "text": (p.get("text") or p.get("snippet") or "")[:300]} for p in (pr.get("posts") or [])[:10]],
                "extensions": pr.get("extensions"), "service_options": pr.get("service_options"),
                "website": pr.get("website") or base.get("website"), "phone": pr.get("phone") or base.get("phone"),
                "address": pr.get("address") or base.get("address"), "rating": pr.get("rating", base.get("rating")), "reviews": pr.get("reviews", base.get("reviews")),
                "user_reviews_summary": pr.get("user_reviews", {}).get("summary") if isinstance(pr.get("user_reviews"), dict) else None,
                "questions_and_answers": len(pr.get("questions_and_answers") or []),
            }
    except Exception as e:  # noqa: BLE001
        out["details_error"] = str(e)[:160]
    if want_reviews and (base.get("data_id") or base.get("place_id")):
        try:
            params = {"engine": "google_maps_reviews", "hl": cfg.get("hl", "en"), "sort_by": "newestFirst"}
            if base.get("data_id"):
                params["data_id"] = base["data_id"]
            else:
                params["place_id"] = base["place_id"]
            d = serpapi_search(params, key)
            revs = []
            for r in d.get("reviews") or []:
                resp = r.get("response") or {}
                revs.append({"user": (r.get("user") or {}).get("name"), "rating": r.get("rating"), "date": r.get("date"), "iso_date": r.get("iso_date"),
                             "snippet": (r.get("snippet") or "")[:400], "likes": r.get("likes"),
                             "response": {"date": resp.get("date"), "snippet": (resp.get("snippet") or "")[:200]} if resp else None})
            out["recent_reviews"] = revs
            pi = d.get("place_info") or {}
            if pi.get("rating"):
                out["rating"] = pi.get("rating")
            if pi.get("reviews"):
                out["reviews"] = pi.get("reviews")
        except Exception as e:  # noqa: BLE001
            out["reviews_error"] = str(e)[:160]
    return out


def serp_yelp(brand: str, location: str, key: str | None, cfg: dict) -> dict:
    if not serp_ok(key):
        return {"available": False, "reason": "no SERPAPI_API_KEY"}
    try:
        d = serpapi_search({"engine": "yelp", "find_desc": brand, "find_loc": location}, key)
    except Exception as e:  # noqa: BLE001
        return {"available": False, "reason": str(e)[:160]}
    key_b = _norm(brand)
    for r in d.get("organic_results") or []:
        if key_b and key_b in _norm(r.get("title", "")) or _norm(r.get("title", "")) in key_b:
            return {"available": True, "found": True, "title": r.get("title"), "rating": r.get("rating"), "reviews": r.get("reviews"),
                    "categories": [c.get("title") for c in (r.get("categories") or []) if isinstance(c, dict)], "phone": r.get("phone"),
                    "neighborhoods": r.get("neighborhoods"), "link": r.get("link"), "price": r.get("price")}
    return {"available": True, "found": False}


def serp_gbp(brand: str, location: str, domain: str, key: str | None, cfg: dict) -> dict:
    if not serp_ok(key):
        return {"available": False, "reason": "no SERPAPI_API_KEY"}
    try:
        d = serpapi_search({"engine": "google_maps", "q": f"{brand} {location.split(',')[0]}", "type": "search",
                            "hl": cfg.get("hl", "en"), "gl": cfg.get("gl", "au")}, key)
    except Exception as e:  # noqa: BLE001
        return {"available": False, "reason": str(e)[:160]}
    places = d.get("local_results") or ([d["place_results"]] if d.get("place_results") else [])
    match = None
    for p in places:
        if domain in (p.get("website") or "").lower():
            match = p
            break
    if not match and places:
        match = places[0]
        match["_unverified_match"] = True
    if not match:
        return {"available": True, "found": False}
    return {"available": True, "found": True, "title": match.get("title"), "rating": match.get("rating"),
            "reviews": match.get("reviews"), "address": match.get("address"), "phone": match.get("phone"),
            "website": match.get("website"), "type": match.get("type") or (match.get("types") or [None])[0], "types": match.get("types") or [],
            "hours": match.get("hours") or match.get("operating_hours"), "unverified": bool(match.get("_unverified_match")),
            "place_id": match.get("place_id"), "data_id": match.get("data_id"), "description": match.get("description"),
            "thumbnail": match.get("thumbnail"), "gps": match.get("gps_coordinates")}


def wikipedia(domain: str, brand: str) -> dict:
    out = {"available": True, "links_to_site": [], "brand_pages": []}
    try:
        r = get("https://en.wikipedia.org/w/api.php", params={"action": "query", "list": "exturlusage", "euquery": domain,
                                                             "euprotocol": "https", "eulimit": 10, "format": "json"})
        out["links_to_site"] = [{"title": x.get("title"), "url": x.get("url")} for x in r.json().get("query", {}).get("exturlusage", [])]
        r2 = get("https://en.wikipedia.org/w/api.php", params={"action": "query", "list": "search", "srsearch": f'"{brand}"',
                                                              "srlimit": 5, "format": "json"})
        out["brand_pages"] = [x.get("title") for x in r2.json().get("query", {}).get("search", [])]
    except Exception as e:  # noqa: BLE001
        out = {"available": False, "reason": str(e)[:160]}
    return out


def youtube_channel(url: str | None) -> dict:
    if not url:
        return {"linked": False}
    try:
        r = get(url, headers={"Accept-Language": "en"})
        m = re.search(r"([\d.,]+[KM]?)\s+subscribers", r.text)
        return {"linked": True, "url": url, "subscribers": m.group(1) if m else None}
    except Exception as e:  # noqa: BLE001
        return {"linked": True, "url": url, "error": str(e)[:120]}


def gemini_prompts(prompts: list[str], brand: str, domain: str, key: str | None) -> dict:
    if not key and not RELAY:
        return {"available": False, "reason": "no GEMINI_API_KEY"}
    if not prompts:
        return {"available": False, "reason": "no prompts supplied"}
    rows, errors = [], []
    for p in prompts:
        body = {"contents": [{"parts": [{"text": p + "\n\nAnswer with a numbered list of specific businesses (name and website if known), best first. Then one sentence on why."}]}],
                "tools": [{"google_search": {}}]}
        try:
            r = None
            for attempt in range(4):
                if key:
                    r = SESSION.post(f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}",
                                     json=body, timeout=120)
                else:
                    r = relay_post("/gemini", {"model": "gemini-2.5-flash", "body": body}, timeout=150)
                if r.status_code in (429, 503) and attempt < 3:
                    time.sleep(20 * (attempt + 1))
                    continue
                break
            time.sleep(4)
            if r.status_code != 200:
                errors.append(f"{p[:40]}: HTTP {r.status_code} {r.text[:120]}")
                continue
            d = r.json()
            text = "".join(pt.get("text", "") for pt in d["candidates"][0]["content"]["parts"])
            gm = d["candidates"][0].get("groundingMetadata", {})
            cites = [c.get("web", {}).get("uri", "") for c in gm.get("groundingChunks", [])]
            rows.append(analyze_answer(p, text, brand, domain, cites))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{p[:40]}: {e}")
    return {"available": True, "engine": "gemini", "rows": rows, "errors": errors}


def analyze_answer(prompt: str, text: str, brand: str, domain: str, cites: list[str] | None = None) -> dict:
    names = []
    for line in text.splitlines():
        m = re.match(r"^\s*(\d+)[.)]\s*\**([^*\n:(\-–—]+)", line)
        if m:
            names.append(m.group(2).strip().strip("*").strip())
    bl = brand.lower()
    key = re.sub(r"[^a-z0-9]", "", bl)
    mentioned = bl in text.lower() or domain in text.lower() or any(key in re.sub(r"[^a-z0-9]", "", n.lower()) for n in names)
    rank = next((i + 1 for i, n in enumerate(names) if key in re.sub(r"[^a-z0-9]", "", n.lower())), None)
    return {"prompt": prompt, "mentioned": mentioned, "rank": rank, "businesses": names[:10],
            "cited_domain": any(domain in (c or "").lower() for c in (cites or [])), "answer_excerpt": text[:600]}


# ----------------------------------------------------------------------------- crawl


def crawl_site(start: str, max_pages: int) -> dict:
    seen, queue, pages = set(), [start], []
    d = domain_of(start)
    while queue and len(pages) < max_pages:
        u = queue.pop(0)
        if u in seen:
            continue
        seen.add(u)
        try:
            r = get(u)
        except Exception as e:  # noqa: BLE001
            pages.append({"url": u, "status": None, "error": str(e)[:100]})
            continue
        ct = r.headers.get("content-type", "")
        if "text/html" not in ct:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        title = soup.title.get_text(strip=True) if soup.title else ""
        md = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
        h1 = [h.get_text(" ", strip=True) for h in soup.find_all("h1")]
        text = visible_text(soup)
        imgs = soup.find_all("img")
        missing = len([i for i in imgs if not (i.get("alt") or "").strip() and not (i.get("src") or "").startswith("data:")])
        robots = " ".join(m.get("content", "") for m in soup.find_all("meta", attrs={"name": re.compile("^robots$", re.I)}))
        canon = soup.find("link", rel="canonical")
        pages.append({
            "url": u, "status": r.status_code, "title": title, "title_length": len(title),
            "meta_description_length": len((md.get("content") or "").strip()) if md else 0,
            "h1_count": len(h1), "word_count": len(words(text)), "images": len(imgs), "images_missing_alt": missing,
            "noindex": "noindex" in robots.lower(), "canonical": canon.get("href") if canon else None,
        })
        for a in soup.find_all("a", href=True):
            href = urljoin(u, a["href"].split("#")[0])
            if href.startswith("http") and domain_of(href) == d and href not in seen and not re.search(r"\.(pdf|jpg|jpeg|png|gif|svg|webp|zip|mp4|css|js)$", href, re.I):
                queue.append(href)
    return {"pages": pages, "count": len(pages), "truncated": bool(queue)}


# ----------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out", required=True)
    ap.add_argument("--keywords", default="")
    ap.add_argument("--prompts", default="")
    ap.add_argument("--brand", default="")
    ap.add_argument("--location", default=None)
    ap.add_argument("--google-domain", default="", help="Override google_domain from config.json, e.g. google.it")
    ap.add_argument("--gl", default="", help="Override country code from config.json, e.g. it")
    ap.add_argument("--hl", default="", help="Override language code from config.json, e.g. it")
    ap.add_argument("--crawl", type=int, default=0)
    ap.add_argument("--skip-external", action="store_true")
    ap.add_argument("--skip-cc", action="store_true")
    ap.add_argument("--skip-psi", action="store_true")
    ap.add_argument("--skip-browser", action="store_true")
    ap.add_argument("--external-only", action="store_true", help="Reuse an existing data.json and only (re)run external metrics")
    ap.add_argument("--local-keyword", default="", help="Primary local keyword for the GBP keyword checks, e.g. 'marketing agency'")
    ap.add_argument("--local", action="store_true", help="Also fetch full Google Business Profile details, newest reviews and Yelp listing (3 extra SerpApi searches)")
    args = ap.parse_args()

    cfg = load_config()
    defaults = dict(cfg.get("defaults", {}))
    if args.google_domain:
        defaults["google_domain"] = args.google_domain
    if args.gl:
        defaults["gl"] = args.gl
    if args.hl:
        defaults["hl"] = args.hl
    keys = load_keys()
    if keys.get("RELAY_URL") and keys.get("RELAY_TOKEN"):
        RELAY.update({"url": keys["RELAY_URL"], "token": keys["RELAY_TOKEN"]})
        log(f"using key relay at {keys['RELAY_URL']}")
    url = normalize_url(args.url)
    domain = domain_of(url)
    out_dir = Path(os.path.expanduser(args.out))
    out_dir.mkdir(parents=True, exist_ok=True)
    location = args.location or defaults.get("location", "Australia")
    keywords = [k.strip() for k in args.keywords.split(";") if k.strip()]
    prompts = [p.strip() for p in args.prompts.split(";") if p.strip()]

    if args.external_only:
        from common import read_json
        data = read_json(out_dir / "data.json")
        if not data:
            log("no data.json to extend; run without --external-only first")
            return 1
        brand = args.brand or data.get("brand") or domain
        data["brand"] = brand
        data["location"] = location
        log("external metrics only")
        data["external"] = run_external(url, domain, brand, keywords, prompts, keys, defaults, location, args)
        data["keywords_requested"] = keywords
        data["prompts_requested"] = prompts
        data["local_keyword"] = args.local_keyword
        write_json(out_dir / "data.json", data)
        log(f"done -> {out_dir / 'data.json'}")
        return 0

    data: dict = {"url": url, "domain": domain, "collected_at": time.strftime("%Y-%m-%d %H:%M"), "location": location,
                  "keys_present": sorted(k for k in keys), "warnings": []}

    log(f"fetching {url}")
    raw = fetch_raw(url)
    data["fetch"] = {k: v for k, v in raw.items() if k != "html"}
    html = raw["html"]
    if raw["status"] >= 400 or not html:
        data["warnings"].append(f"page returned status {raw['status']}")

    log("security / robots / sitemap / llms / dns")
    data["https"] = https_checks(url)
    data["robots"] = fetch_robots(url)
    data["sitemap"] = fetch_sitemap(url, data["robots"])
    data["llms_txt"] = fetch_llms(url)
    data["dns"] = dns_checks(domain)
    data["x_robots_tag"] = raw["headers"].get("x-robots-tag")
    data["noindex_header"] = "noindex" in (raw["headers"].get("x-robots-tag") or "").lower()
    data["server"] = raw["headers"].get("server")
    data["hsts"] = bool(raw["headers"].get("strict-transport-security"))
    data["alt_svc_h3"] = "h3" in (raw["headers"].get("alt-svc") or "")
    data["content_encoding"] = raw["headers"].get("content-encoding")
    data["charset"] = raw["headers"].get("content-type")

    browser = {"rendered_html": "", "rendered_text": "", "resources": [], "timing": {}, "js_errors": [], "screenshots": {}}
    if not args.skip_browser:
        log("browser pass (screenshots, resources, timings)")
        try:
            browser = browser_pass(url, out_dir / "shots")
        except Exception as e:  # noqa: BLE001
            import traceback
            data["warnings"].append(f"browser pass failed: {str(e)[:200]}")
            log("browser pass failed:\n" + traceback.format_exc()[-1500:])
    data["browser"] = {k: v for k, v in browser.items() if k not in ("rendered_html", "rendered_text", "resources")}
    data["resources"] = summarize_resources(browser.get("resources", []))

    log("parsing page")
    data["page"] = parse_page(url, html, browser.get("rendered_html", ""), browser.get("rendered_text", ""))
    net = network_signals(browser.get("resources", []))
    data["network"] = net
    pg = data["page"]
    pg["facebook_pixel"] = pg.get("facebook_pixel") or net["facebook_pixel"]
    if net["ga_ids"] or "Google Analytics" in net["tech"]:
        pg["analytics"] = sorted(set(pg["analytics"] + ["Google Analytics"]))
    if "Google Tag Manager" in net["tech"]:
        pg["analytics"] = sorted(set(pg["analytics"] + ["Google Tag Manager"]))
    if "Cloudflare" in net["tech"] or "cloudflare" in (data.get("server") or "").lower():
        net["tech"].append("Cloudflare")
    if data.get("hsts"):
        net["tech"].append("HSTS")
    if data.get("alt_svc_h3") or "h3" in data["resources"].get("protocols", {}):
        net["tech"].append("HTTP/3")
    pg["tech"] = sorted(set(pg["tech"] + net["tech"]))
    soup = BeautifulSoup(html, "lxml")
    data["favicon"] = favicon_check(url, soup)
    brand = args.brand or guess_brand(data["page"], domain)
    data["brand"] = brand
    data["page"]["youtube"] = youtube_channel(data["page"]["social"].get("youtube"))

    if args.crawl:
        log(f"crawling up to {args.crawl} pages")
        data["crawl"] = crawl_site(url, args.crawl)

    data["external"] = {} if args.skip_external else run_external(url, domain, brand, keywords, prompts, keys, defaults, location, args)
    data["keywords_requested"] = keywords
    data["prompts_requested"] = prompts
    data["local_keyword"] = args.local_keyword

    write_json(out_dir / "data.json", data)
    (out_dir / "raw.html").write_text(html)
    if browser.get("rendered_html"):
        (out_dir / "rendered.html").write_text(browser["rendered_html"])
    log(f"done -> {out_dir / 'data.json'}")
    return 0


def run_external(url, domain, brand, keywords, prompts, keys, defaults, location, args) -> dict:
    log("external metrics")
    ext: dict = {}
    ext["ahrefs"] = ahrefs_dr(domain, keys.get("AHREFS_API_KEY"))
    ext["openpagerank"] = openpagerank([domain], keys.get("OPENPAGERANK_API_KEY"))
    ext["commoncrawl"] = {"available": False, "reason": "skipped"} if args.skip_cc else commoncrawl(domain)
    if not args.skip_psi:
        ext["pagespeed_mobile"] = pagespeed(url, keys.get("GOOGLE_API_KEY"), "mobile")
        ext["pagespeed_desktop"] = pagespeed(url, keys.get("GOOGLE_API_KEY"), "desktop")
    ext["rankings"] = serp_rankings(domain, keywords[: int(defaults.get("max_keywords", 8))], keys.get("SERPAPI_API_KEY"), defaults, location)
    ext["citations"] = serp_citations(domain, brand, keys.get("SERPAPI_API_KEY"), defaults)
    ext["citations"]["wikipedia"] = wikipedia(domain, brand)
    if getattr(args, "local", False):
        ext["gbp"] = serp_gbp_full(brand, location, domain, keys.get("SERPAPI_API_KEY"), defaults)
        ext["yelp"] = serp_yelp(brand, location, keys.get("SERPAPI_API_KEY"), defaults)
    else:
        ext["gbp"] = serp_gbp(brand, location, domain, keys.get("SERPAPI_API_KEY"), defaults)
    ext["gemini"] = gemini_prompts(prompts[: int(defaults.get("max_prompts", 10))], brand, domain, keys.get("GEMINI_API_KEY"))
    return ext


def guess_brand(page: dict, domain: str) -> str:
    for b in page.get("schema_types", []):
        pass
    blk = page.get("local_schema_block")
    if blk and blk.get("name"):
        return str(blk["name"])
    t = page.get("title") or ""
    part = re.split(r"\s[|\-–—:]\s", t)[0].strip()
    if 2 < len(part) < 40:
        return part
    return domain.split(".")[0].title()


if __name__ == "__main__":
    sys.exit(main())
