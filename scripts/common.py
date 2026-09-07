"""Shared helpers for the Adcraft SEO report skill."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

SKILL_DIR = Path(__file__).resolve().parent.parent
KEYS_PATH = Path(os.path.expanduser("~/.config/adcraft-seo/keys.env"))
CONFIG_PATH = SKILL_DIR / "config.json"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 AdcraftSEOReport/1.0"
)


def load_keys() -> dict:
    keys: dict = {}
    if KEYS_PATH.exists():
        for line in KEYS_PATH.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if v:
                keys[k.strip()] = v
    # environment overrides
    for k in list(os.environ):
        if k.endswith("_API_KEY") or k.endswith("_API_TOKEN"):
            keys.setdefault(k, os.environ[k])
    return keys


def load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}


def normalize_url(url: str) -> str:
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    p = urlparse(url)
    path = p.path or "/"
    return f"{p.scheme}://{p.netloc}{path}" + (f"?{p.query}" if p.query else "")


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    host = host.split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def same_site(a: str, b: str) -> bool:
    return domain_of(a) == domain_of(b)


def write_json(path: Path | str, data) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False))


def read_json(path: Path | str, default=None):
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text())


STOPWORDS = set(
    """a about above after again against all am an and any are as at be because been before being below
    between both but by can could did do does doing down during each few for from further had has have having
    he her here hers herself him himself his how i if in into is it its itself just let me more most my myself
    no nor not now of off on once only or other our ours ourselves out over own same she should so some such
    than that the their theirs them themselves then there these they this those through to too under until up
    very was we were what when where which while who whom why will with would you your yours yourself yourselves
    us get one also new like via per via etc use using used make made may might must shall""".split()
)
