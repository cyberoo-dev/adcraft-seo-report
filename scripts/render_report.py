#!/usr/bin/env python3
"""Render report.json into a branded, SEOptimer-style HTML report and an A4 PDF.

Usage: render_report.py <run_dir> [--no-pdf] [--white-label "Client Name"]
Writes: <run_dir>/report.html and <run_dir>/report.pdf
"""
from __future__ import annotations

import argparse
import base64
import html
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import SKILL_DIR, read_json  # noqa: E402

DIAL_COLORS = ["#e94b7a", "#8e5bd8", "#2ec27e", "#f2c12e", "#2f80ed"]
ACCENT = "#2f80ed"


def e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def score_color(score: int | None) -> str:
    if score is None:
        return "#c8ccd4"
    if score >= 85:
        return "#2ec27e"
    if score >= 70:
        return ACCENT
    if score >= 55:
        return "#f2c12e"
    return "#e94b4b"


def dial(score: int | None, size: int = 110, color: str | None = None, stroke: int = 8, label: str | None = None, font: int | None = None) -> str:
    color = color or score_color(score)
    r = (size - stroke) / 2
    circ = 2 * math.pi * r
    val = 0 if score is None else max(0, min(100, score))
    dash = circ * val / 100
    font = font or int(size * 0.3)
    txt = "–" if score is None else str(score)
    svg = (f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" class="dial">'
           f'<circle cx="{size/2}" cy="{size/2}" r="{r}" fill="none" stroke="#e9eef6" stroke-width="{stroke}"/>'
           f'<circle cx="{size/2}" cy="{size/2}" r="{r}" fill="none" stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
           f'stroke-dasharray="{dash:.2f} {circ:.2f}" transform="rotate(-90 {size/2} {size/2})"/>'
           f'<text x="50%" y="50%" dy="0.36em" text-anchor="middle" font-family="Montserrat, Arial, sans-serif" font-weight="500" font-size="{font}" fill="#2b2f36">{txt}</text></svg>')
    if label:
        svg = f'<div class="dialwrap"><div>{svg}</div><div class="diallabel" style="color:{color}">{e(label)}</div></div>'
    return svg


def radar(dials: list[dict], size: int = 220) -> str:
    n = len(dials)
    W = size + 90
    cx, cy = W / 2, size / 2
    R = size / 2 - 34
    pts, labels, rings = [], [], []
    for i, d in enumerate(dials):
        ang = -math.pi / 2 + i * 2 * math.pi / n
        v = (d["score"] or 0) / 100
        pts.append((cx + R * v * math.cos(ang), cy + R * v * math.sin(ang)))
        lx, ly = cx + (R + 22) * math.cos(ang), cy + (R + 16) * math.sin(ang)
        anchor = "middle" if abs(math.cos(ang)) < 0.2 else ("start" if math.cos(ang) > 0 else "end")
        labels.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" font-size="9" fill="#6b7280" font-family="Roboto, Arial, sans-serif">{e(d["label"])}</text>')
    for k in (0.25, 0.5, 0.75, 1.0):
        ring = " ".join(f"{cx + R*k*math.cos(-math.pi/2 + i*2*math.pi/n):.1f},{cy + R*k*math.sin(-math.pi/2 + i*2*math.pi/n):.1f}" for i in range(n))
        rings.append(f'<polygon points="{ring}" fill="none" stroke="#dfe4ec" stroke-width="1"/>')
    spokes = "".join(f'<line x1="{cx}" y1="{cy}" x2="{cx + R*math.cos(-math.pi/2 + i*2*math.pi/n):.1f}" y2="{cy + R*math.sin(-math.pi/2 + i*2*math.pi/n):.1f}" stroke="#dfe4ec" stroke-width="1"/>' for i in range(n))
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="{ACCENT}"/>' for x, y in pts)
    return (f'<svg width="{W}" height="{size}" viewBox="0 0 {W} {size}">{"".join(rings)}{spokes}'
            f'<polygon points="{poly}" fill="rgba(47,128,237,0.25)" stroke="{ACCENT}" stroke-width="1.5"/>{dots}{"".join(labels)}</svg>')


def img_data(path: str | None) -> str | None:
    if not path or not Path(path).exists():
        return None
    b = Path(path).read_bytes()
    ext = Path(path).suffix.lower().lstrip(".")
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "svg": "image/svg+xml", "webp": "image/webp"}.get(ext, "image/png")
    return f"data:{mime};base64," + base64.b64encode(b).decode()


def status_icon(status: str) -> str:
    if status == "pass":
        return '<svg width="26" height="26" viewBox="0 0 26 26"><path d="M5 13.5l5 5L21 8" fill="none" stroke="#2ec27e" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    if status == "fail":
        return '<svg width="26" height="26" viewBox="0 0 26 26"><path d="M6 6l14 14M20 6L6 20" fill="none" stroke="#e94b4b" stroke-width="3" stroke-linecap="round"/></svg>'
    if status == "warn":
        return '<svg width="26" height="26" viewBox="0 0 26 26"><path d="M13 4L23 22H3z" fill="none" stroke="#f2a33a" stroke-width="2.5" stroke-linejoin="round"/><path d="M13 11v5" stroke="#f2a33a" stroke-width="2.5" stroke-linecap="round"/><circle cx="13" cy="19" r="1.4" fill="#f2a33a"/></svg>'
    return '<span class="info-i">i</span>'


def pill(text: str, kind: str = "grey") -> str:
    return f'<span class="pill pill-{kind}">{e(text)}</span>'


def prio_pill(p: str) -> str:
    k = {"High Priority": "red", "Medium Priority": "yellow", "Low Priority": "green"}.get(p, "grey")
    return pill(p, k)


# --------------------------------------------------------------------------- check renderers


def details_box(items: list[str]) -> str:
    if not items:
        return ""
    return "".join(f'<div class="dbox">{e(x).replace(chr(10), "<br>")}</div>' for x in items if x)


def render_kind(c: dict) -> str:
    k = c.get("kind", "row")
    x = c.get("extra", {})
    if k == "serp":
        fav = f'<img src="{e(x.get("favicon"))}" class="serp-fav" alt="">' if x.get("favicon") else '<span class="serp-fav serp-fav-ph"></span>'
        return (f'<div class="serp">{fav}<div class="serp-brand">{e(x.get("brand"))}<div class="serp-url">{e(x.get("url"))}</div></div>'
                f'<div class="serp-title">{e(x.get("title"))}</div><div class="serp-desc">{e(x.get("description"))}</div></div>')
    if k == "tagtable":
        rows = "".join(f'<tr><td class="mono">{e(r[0])}</td><td>{e(r[1])}</td></tr>' for r in x.get("rows", []))
        return f'<table class="mini"><thead><tr><th>Tag</th><th>Value</th></tr></thead><tbody>{rows}</tbody></table>'
    if k == "headings":
        mx = max([f[1] for f in x.get("freq", [])] + [1])
        freq = "".join(f'<tr><td class="mono">{e(f[0])}</td><td>{f[1]}</td><td><div class="bar" style="width:{int(120*f[1]/mx)}px"></div></td></tr>' for f in x.get("freq", []))
        rows = "".join(f'<tr><td class="mono">{e(r[0])}</td><td>{e(r[1])}</td></tr>' for r in x.get("rows", [])[:30])
        return (f'<table class="mini"><thead><tr><th>Header Tag</th><th>Frequency</th><th></th></tr></thead><tbody>{freq}</tbody></table>'
                f'<table class="mini"><thead><tr><th>Tag</th><th>Value</th></tr></thead><tbody>{rows}</tbody></table>')
    if k == "keywords":
        def tbl(title, rows):
            tick = '<span class="kw-tick">✓</span>'
            body = "".join(f'<tr><td>{e(r["keyword"])}</td><td class="c">{tick if r["title"] else ""}</td><td class="c">{tick if r["meta"] else ""}</td><td class="c">{tick if r["headings"] else ""}</td><td class="c">{r["frequency"]}</td></tr>' for r in rows)
            return f'<div class="kw-title">{title}</div><table class="mini kw"><thead><tr><th>Keyword</th><th>Title</th><th>Meta Description</th><th>Headings</th><th>Page Frequency</th></tr></thead><tbody>{body}</tbody></table>'
        return tbl("Individual Keywords", x.get("keywords", [])) + (tbl("Phrases", x["phrases"]) if x.get("phrases") else "")
    if k == "imagelist":
        rows = "".join(f'<tr><td>{i+1}</td><td class="wrap">{e(u.replace("https://", "").replace("http://", ""))}</td></tr>' for i, u in enumerate(x.get("images", [])))
        return f'<table class="mini"><thead><tr><th>#</th><th>Image Link</th></tr></thead><tbody>{rows}</tbody></table>'
    if k == "metrics":
        ms = x.get("metrics", [])
        if not ms:
            return ""
        cells = []
        for m in ms:
            if m.get("raw"):
                cells.append(f'<div class="metric"><div class="metric-big">{e(f"{m["value"]:,}" if isinstance(m["value"], (int, float)) else m["value"])}</div><div class="metric-label">{e(m["label"])}</div><div class="metric-src">{e(m.get("source", ""))}</div></div>')
            else:
                cells.append(f'<div class="metric">{dial(m["value"], 84, ACCENT, 7, font=24)}<div class="metric-label">{e(m["label"])}</div><div class="metric-src">{e(m.get("display") or "")} {e(m.get("source", ""))}</div></div>')
        return f'<div class="metrics">{"".join(cells)}</div>'
    if k == "history":
        h = x.get("history", [])
        vals = [float(p.get("open_page_rank") or p.get("page_rank_decimal") or 0) for p in h]
        if not vals:
            return ""
        mx = max(vals) or 1
        bars = "".join(f'<div class="hbar" title="{e(p.get("date", ""))}"><div style="height:{int(50*v/mx)}px"></div><span>{e(str(p.get("date", ""))[:7])}</span></div>' for p, v in zip(h, vals))
        return f'<div class="hist">{bars}</div>'
    if k == "links":
        ln = x.get("links", {})
        rows = "".join(f'<tr><td class="wrap">{e(l["url"])}</td><td>{e(l["type"])}</td><td>{e(l["follow"])}</td></tr>' for l in ln.get("list", [])[:60])
        return (f'<div class="metrics small"><div class="metric"><div class="metric-big">{ln.get("total", 0)}</div><div class="metric-label">Total</div></div>'
                f'<div class="metric"><div class="metric-big">{ln.get("internal", 0)}</div><div class="metric-label">Internal Links</div></div>'
                f'<div class="metric"><div class="metric-big">{ln.get("external_follow", 0)}</div><div class="metric-label">External Links: Follow</div></div>'
                f'<div class="metric"><div class="metric-big">{ln.get("external_nofollow", 0)}</div><div class="metric-label">External Links: Nofollow</div></div></div>'
                f'<table class="mini"><thead><tr><th>Page</th><th>Type</th><th>Follow / Nofollow</th></tr></thead><tbody>{rows}</tbody></table>')
    if k == "devices":
        shots = x.get("shots", {})
        cells = []
        for name, w in (("desktop", 300), ("tablet", 150), ("mobile", 90)):
            src = img_data(shots.get(name))
            if src:
                cells.append(f'<div class="device device-{name}"><img src="{src}" alt="{name}"><div class="device-label">{name.title()}</div></div>')
        return f'<div class="devices">{"".join(cells)}</div>'
    if k == "cwv":
        cells = "".join(f'<div class="metric"><div class="metric-big" style="color:{ {"FAST": "#2ec27e", "AVERAGE": "#f2a33a", "SLOW": "#e94b4b"}.get(m["cat"], "#2b2f36") }">{e(m["value"])}{e(m["unit"])}</div><div class="metric-label">{e(m["label"])}</div><div class="metric-src">{e(m["cat"].title())}</div></div>' for m in x.get("metrics", []))
        return f'<div class="metrics">{cells}</div>'
    if k in ("timing", "resources"):
        cells = "".join(f'<div class="metric"><div class="metric-big">{e(m["value"])}</div><div class="metric-label">{e(m["label"])}</div></div>' for m in x.get("metrics", []))
        return f'<div class="metrics{" small" if k == "resources" else ""}">{cells}</div>'
    if k == "size":
        rows = "".join(f'<tr><td>{e(b["label"])}</td><td>{e(b["value"])}</td></tr>' for b in x.get("breakdown", []))
        return (f'<div class="metrics"><div class="metric"><div class="metric-big">{e(x.get("total"))}</div><div class="metric-label">Download Page Size</div></div>'
                f'<div class="metric wide"><div class="metric-label">Download Page Size Breakdown</div><table class="mini"><tbody>{rows}</tbody></table></div></div>')
    if k == "compression":
        rows = "".join(f'<tr><td>{e(r["label"])}</td><td>{r["pct"]}% compressed of {e(r["raw"])}</td></tr>' for r in x.get("rows", []))
        return (f'<div class="metrics"><div class="metric">{dial(x.get("total", 0), 84, ACCENT, 7, font=22)}<div class="metric-label">Compression Rate</div></div>'
                f'<div class="metric wide"><div class="metric-label">Compression Rates</div><table class="mini"><tbody>{rows}</tbody></table></div></div>')
    if k == "techlist":
        items = "".join(f"<li>{e(t)}</li>" for t in x.get("tech", []))
        return f'<ul class="techlist">{items}</ul>'
    if k == "schema":
        rows = "".join(f'<tr><td class="mono" style="padding-left:{8 + 10*(len(r[0]) - len(r[0].lstrip()))}px">{e(r[0].strip())}</td><td class="wrap">{e(r[1])}</td></tr>' for r in x.get("rows", []))
        return f'<div class="dbox">{e(", ".join(x.get("types", [])))}</div><table class="mini"><tbody>{rows}</tbody></table>'
    if k == "reviews":
        r, n = x.get("rating"), x.get("count")
        stars = "★" * int(round(r or 0)) + "☆" * (5 - int(round(r or 0)))
        return f'<div class="metrics small"><div class="metric"><div class="metric-big">{e(r)} <span class="stars">{stars}</span></div><div class="metric-label">{e(n)} reviews</div></div></div>'
    if k == "rankings":
        rows = "".join(f'<tr><td>{e(r["keyword"])}</td><td>{e(x.get("location", ""))}</td><td class="c">{e(r["position"] if r["position"] else "100+")}</td><td class="c">{"Yes" if r.get("ai_overview") else "–"}</td><td class="c">{"Cited" if r.get("ai_overview_cited") else ("No" if r.get("ai_overview") else "–")}</td><td class="c">{e("#" + str(r["local_pack_position"]) if r.get("local_pack_position") else "–")}</td></tr>' for r in x.get("rows", []))
        return f'<table class="mini"><thead><tr><th>Keyword</th><th>Location</th><th>Position</th><th>AI Overview</th><th>Cited in AIO</th><th>Local Pack</th></tr></thead><tbody>{rows}</tbody></table>'
    if k == "positions":
        rows = "".join(f'<tr><td>{e(k2)}</td><td class="c">{v}</td></tr>' for k2, v in x.get("buckets", {}).items())
        return f'<table class="mini narrow"><thead><tr><th>Position</th><th>Keywords</th></tr></thead><tbody>{rows}</tbody></table>'
    if k == "competitors":
        rows = "".join(f'<tr><td>{e(r["name"])}</td><td class="c">{r["rate"]}%</td><td class="c">{r["avg_pos"]}</td></tr>' for r in x.get("rows", []))
        return f'<table class="mini narrow"><thead><tr><th>Competitor</th><th>Citation Rate</th><th>Average Position</th></tr></thead><tbody>{rows}</tbody></table>'
    if k == "promptgrid":
        eng = x.get("engines", [])
        head = "".join(f"<th>{e(en)}</th>" for en in eng)
        rows = []
        for r in x.get("rows", []):
            cells = []
            for en in eng:
                cell = r["cells"].get(en, {})
                rank = cell.get("rank")
                badge = f'<span class="rankbadge">#{rank}</span>' if rank else ('<span class="rankbadge mentioned">mentioned</span>' if cell.get("mentioned") else '<span class="rankbadge none">–</span>')
                lst = "".join(f"<li>{e(b)}</li>" for b in cell.get("businesses", []))
                cells.append(f'<td>{badge}<ol class="plist">{lst}</ol></td>')
            rows.append(f'<tr><td class="prompt">{e(r["prompt"])}</td>{"".join(cells)}</tr>')
        return f'<table class="mini grid"><thead><tr><th>Prompt</th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>'
    return ""


def render_check(c: dict) -> str:
    st = c["status"]
    body = render_kind(c)
    details = details_box(c.get("details", [])) if c.get("kind", "row") in ("row", "metrics", "history") or not body else ""
    if c.get("kind") == "metrics" and c.get("details"):
        details = details_box(c["details"])
    expl = ""
    if c.get("what") or c.get("how"):
        expl = '<div class="explain">' + (f"<p>{e(c['what'])}</p>" if c.get("what") else "") + (f"<p>{e(c['how'])}</p>" if c.get("how") else "") + "</div>"
    return (f'<div class="check check-{st}"><div class="check-head"><div class="check-text"><div class="check-title">{e(c["title"])}</div>'
            f'<div class="check-summary">{e(c["summary"])}</div></div><div class="check-icon">{status_icon(st)}</div></div>'
            f'{details}{body}{expl}</div>')


def render_section(s: dict, idx: int) -> str:
    head = f'<div class="bar">{e(s["title"])}</div>'
    top = ""
    if s.get("score") is not None:
        top = (f'<div class="section-top">{dial(s["score"], 96, score_color(s["score"]), 8, font=28)}<div class="section-verdict"><h3>{e(s["verdict"])}</h3>'
               f'<p>{e(s.get("intro") or "")}</p></div></div>')
    elif s.get("intro"):
        top = f'<div class="section-top"><div class="section-verdict"><p>{e(s["intro"])}</p></div></div>'
    checks = "".join(render_check(c) for c in s["checks"])
    return f'<section class="report-section">{head}{top}{checks}</section>'


def render_crawl(r: dict) -> str:
    ci = r.get("crawl_issues")
    if not ci:
        return ""
    iss = "".join(f'<tr><td>{e(i["issue"])}</td><td>{prio_pill(i["priority"] + " Priority")}</td><td class="c">{len(i["pages"])}</td><td class="wrap">{"<br>".join(e(p) for p in i["pages"][:40])}</td></tr>' for i in ci["issues"])
    pages = "".join(f'<tr><td class="wrap">{e(p["page"])}</td><td class="c">{p["count"]}</td><td>{"<br>".join(e(i) for i in p["issues"])}</td></tr>' for p in ci["pages"])
    note = f'<p class="muted">Crawled {ci.get("count")} pages{" (limit reached, more pages exist)" if ci.get("truncated") else ""}.</p>'
    return (f'<section class="report-section"><div class="bar">Issues Found for {e(r["url"])}</div>{note}'
            f'<table class="mini"><thead><tr><th>Issue Type</th><th>Priority</th><th>Pages</th><th>Pages Affected</th></tr></thead><tbody>{iss}</tbody></table></section>'
            f'<section class="report-section"><div class="bar">Crawl Report for {e(r["url"])}</div>'
            f'<table class="mini"><thead><tr><th>Page</th><th>Issues</th><th>Issue List</th></tr></thead><tbody>{pages}</tbody></table></section>')


def render_action_plan(r: dict) -> str:
    plan = r.get("action_plan")
    if not plan:
        return ""
    items = []
    for i, it in enumerate(plan, 1):
        steps = "".join(f"<li>{e(s)}</li>" for s in it.get("steps", []))
        items.append(f'<div class="plan-item"><div class="plan-head"><span class="plan-n">{i}</span><div class="plan-title">{e(it.get("title"))}</div>{prio_pill(it.get("priority", "Medium Priority"))}</div>'
                     f'<p>{e(it.get("why", ""))}</p>{"<ol>" + steps + "</ol>" if steps else ""}'
                     + (f'<p class="muted"><b>Effort:</b> {e(it.get("effort"))} &nbsp; <b>Impact:</b> {e(it.get("impact"))}</p>' if it.get("effort") or it.get("impact") else "") + "</div>")
    return f'<section class="report-section"><div class="bar">Action Plan</div><div class="plan">{"".join(items)}</div></section>'


CSS = """
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;500;600&family=Roboto:wght@300;400;500;700&display=swap');
@page { size: A4; margin: 14mm 12mm 16mm 12mm; }
* { box-sizing: border-box; }
body { font-family: Roboto, Helvetica, Arial, sans-serif; color: #2b2f36; font-size: 11px; line-height: 1.5; margin: 0; background: #fff; }
.page { max-width: 780px; margin: 0 auto; padding: 24px 28px; }
h1, h2, h3, .bar, .diallabel, .check-title, .section-verdict h3 { font-family: Montserrat, Helvetica, Arial, sans-serif; }
.header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 28px; }
.header img.logo { height: 44px; }
.agency { text-align: right; font-size: 11px; line-height: 1.55; color: #2b2f36; }
.agency a { color: #2f80ed; text-decoration: none; display: block; }
h1 { font-weight: 300; font-size: 24px; margin: 6px 0 12px; color: #2b2f36; }
p.intro { color: #6b7280; font-size: 11.5px; line-height: 1.6; margin: 0 0 22px; }
.bar { background: #111; color: #fff; font-size: 17px; font-weight: 400; padding: 11px 16px; margin: 26px 0 18px; page-break-after: avoid; }
.results { display: flex; align-items: center; gap: 30px; margin: 10px 0 20px; }
.results .main { flex: 0 0 300px; text-align: center; }
.results .verdict { font-family: Montserrat, sans-serif; font-size: 15px; margin-top: 8px; font-weight: 400; }
.results .shot { flex: 1; position: relative; min-height: 200px; }
.shot-desktop { width: 300px; border: 6px solid #fff; border-radius: 10px; box-shadow: 0 8px 26px rgba(0,0,0,.18); display: block; margin-left: auto; }
.shot-mobile { width: 78px; border: 4px solid #fff; border-radius: 10px; box-shadow: 0 8px 22px rgba(0,0,0,.22); position: absolute; right: -8px; bottom: -14px; }
.pill { display: inline-block; font-size: 10px; padding: 3px 9px; border-radius: 3px; white-space: nowrap; }
.pill-grey { background: #eef1f5; color: #2b2f36; } .pill-green { background: #e3f8ec; color: #1e9e5a; } .pill-yellow { background: #fff6d6; color: #b8860b; }
.pill-red { background: #fde3e3; color: #d13c3c; } .pill-pink { background: #fde3ea; color: #d43f6b; } .pill-blue { background: #e3edfb; color: #2f80ed; }
.dials { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin: 8px 0 4px; }
.dialrow { display: flex; gap: 14px; }
.dialwrap { text-align: center; } .diallabel { font-size: 10px; margin-top: 4px; font-weight: 500; }
.recs { margin: 4px 0 10px; }
.rec { display: flex; align-items: center; padding: 8px 6px; border-bottom: 1px solid #f0f2f5; page-break-inside: avoid; }
.rec .t { flex: 1; font-family: Montserrat, sans-serif; font-size: 12px; font-weight: 400; } .rec .cat { width: 120px; } .rec .pri { width: 96px; text-align: right; }
.section-top { display: flex; gap: 20px; align-items: center; margin: 0 0 14px; }
.section-verdict h3 { font-size: 14px; font-weight: 400; margin: 0 0 4px; } .section-verdict p { margin: 0; color: #6b7280; }
.check { padding: 10px 14px 10px 24px; margin: 0 0 6px; page-break-inside: avoid; }
.check-head { display: flex; align-items: flex-start; gap: 12px; }
.check-text { flex: 1; } .check-icon { flex: 0 0 28px; text-align: right; padding-top: 2px; }
.check-title { font-size: 13px; font-weight: 400; margin-bottom: 2px; } .check-summary { color: #4b5563; font-size: 11px; }
.info-i { font-family: Georgia, serif; font-style: italic; font-size: 20px; color: #5b8def; }
.dbox { border-top: 1px dashed #d9dee7; border-bottom: 1px dashed #d9dee7; padding: 5px 8px; margin: 8px 0 0; font-size: 10.5px; color: #4b5563; max-width: 560px; word-break: break-word; }
.dbox + .dbox { border-top: none; }
.explain { background: #eef4fd; padding: 10px 12px; margin-top: 10px; color: #4b5563; font-size: 10.5px; line-height: 1.55; }
.explain p { margin: 0 0 6px; } .explain p:last-child { margin: 0; }
table.mini { border-collapse: collapse; font-size: 10px; margin: 8px 0 4px; width: 100%; max-width: 620px; }
table.mini.narrow { max-width: 320px; } table.mini th { text-align: left; color: #6b7280; font-weight: 500; text-transform: uppercase; font-size: 9px; letter-spacing: .04em; padding: 5px 8px; border-bottom: 1px dashed #d9dee7; }
table.mini td { padding: 5px 8px; border-bottom: 1px dashed #e6e9ef; vertical-align: top; color: #4b5563; } td.c, th.c { text-align: center; } td.mono { font-family: Menlo, monospace; font-size: 9.5px; color: #6b7280; white-space: nowrap; width: 1%; }
td.wrap { word-break: break-all; }
.bar-cell { } .bar { } table.mini .bar { display: block; height: 8px; background: #2f80ed; border-radius: 4px; margin: 0; padding: 0; }
.kw-title { font-size: 11px; font-weight: 500; margin-top: 10px; color: #2b2f36; } .kw-tick { color: #2ec27e; font-weight: 700; }
.metrics { display: flex; gap: 26px; align-items: flex-start; margin: 10px 0 4px; flex-wrap: wrap; } .metrics.small .metric-big { font-size: 20px; }
.metric { text-align: center; min-width: 90px; } .metric.wide { text-align: left; min-width: 260px; }
.metric-big { font-family: Montserrat, sans-serif; font-size: 24px; font-weight: 400; color: #2b2f36; } .metric-label { font-size: 10px; color: #6b7280; margin-top: 2px; } .metric-src { font-size: 9px; color: #9aa3b2; }
.hist { display: flex; align-items: flex-end; gap: 6px; height: 70px; margin: 8px 0; } .hbar { text-align: center; } .hbar div { width: 22px; background: #2f80ed; border-radius: 3px 3px 0 0; } .hbar span { font-size: 8px; color: #9aa3b2; display: block; }
.devices { display: flex; align-items: flex-end; gap: 18px; margin: 10px 0; } .device img { border: 4px solid #fff; border-radius: 8px; box-shadow: 0 6px 18px rgba(0,0,0,.16); display: block; }
.device-desktop img { width: 300px; } .device-tablet img { width: 140px; } .device-mobile img { width: 80px; } .device-label { text-align: center; font-size: 9px; color: #6b7280; margin-top: 6px; }
.serp { border: 1px solid #dfe3ea; border-radius: 6px; padding: 10px 12px; margin: 10px 0; max-width: 560px; font-family: Arial, sans-serif; }
.serp-fav { width: 22px; height: 22px; border-radius: 50%; float: left; margin-right: 10px; background: #f1f3f4; } .serp-brand { font-size: 11px; color: #202124; } .serp-url { font-size: 10px; color: #4d5156; }
.serp-title { color: #1a0dab; font-size: 15px; margin: 6px 0 2px; clear: both; } .serp-desc { color: #4d5156; font-size: 11px; }
ul.techlist { columns: 3; list-style: none; padding: 0; margin: 8px 0; font-size: 10.5px; } ul.techlist li { padding: 3px 0; border-bottom: 1px dashed #e6e9ef; break-inside: avoid; }
.stars { color: #f2c12e; font-size: 16px; }
table.grid td.prompt { width: 34%; font-size: 10px; } .rankbadge { display: inline-block; background: #e3edfb; color: #2f80ed; border-radius: 3px; padding: 1px 6px; font-size: 9px; font-weight: 500; }
.rankbadge.mentioned { background: #e3f8ec; color: #1e9e5a; } .rankbadge.none { background: #f3f4f6; color: #9aa3b2; }
ol.plist { margin: 4px 0 0; padding-left: 14px; font-size: 9px; color: #6b7280; } ol.plist li { margin: 0; }
.plan-item { border: 1px solid #e6e9ef; border-radius: 6px; padding: 10px 14px; margin-bottom: 10px; page-break-inside: avoid; }
.plan-head { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; } .plan-n { background: #111; color: #fff; border-radius: 50%; width: 22px; height: 22px; display: inline-flex; align-items: center; justify-content: center; font-size: 11px; }
.plan-title { flex: 1; font-family: Montserrat, sans-serif; font-size: 13px; } .plan-item p { margin: 4px 0; color: #4b5563; } .plan-item ol { margin: 4px 0; padding-left: 18px; color: #4b5563; }
.muted { color: #9aa3b2; font-size: 10px; }
.exec { background: #f7f8fa; border-left: 3px solid #111; padding: 10px 14px; margin: 0 0 18px; color: #4b5563; font-size: 11px; }
.footer { margin-top: 30px; color: #9aa3b2; font-size: 9px; text-align: center; }
"""


def render(run_dir: Path, white_label: str | None = None) -> Path:
    r = read_json(run_dir / "report.json")
    ag = r.get("agency", {})
    logo = img_data(str(SKILL_DIR / ag.get("logo", "assets/adcraft-logo.svg"))) if not white_label else None
    header = ""
    if white_label:
        header = f'<div class="header"><div style="font-family:Montserrat;font-size:20px;font-weight:600">{e(white_label)}</div><div class="agency"></div></div>'
    else:
        header = (f'<div class="header">{f"<img class=logo src={chr(34)}{logo}{chr(34)} alt=logo>" if logo else f"<b>{e(ag.get(chr(110)+chr(97)+chr(109)+chr(101), ""))}</b>"}'
                  f'<div class="agency">{e(ag.get("name", ""))}<br>{e(ag.get("address", ""))}<a href="mailto:{e(ag.get("email", ""))}">{e(ag.get("email", ""))}</a><a href="{e(ag.get("website", ""))}">{e(ag.get("website", ""))}</a></div></div>')
    shots = r.get("screenshots", {})
    desk, mob = img_data(shots.get("desktop")), img_data(shots.get("mobile"))
    shot_html = ""
    if desk:
        shot_html = f'<div class="shot"><img class="shot-desktop" src="{desk}" alt="desktop">' + (f'<img class="shot-mobile" src="{mob}" alt="mobile">' if mob else "") + "</div>"
    recs = r.get("recommendations", [])
    recs_html = "".join(f'<div class="rec"><div class="t">{e(x["title"])}</div><div class="cat">{pill(x["category"])}</div><div class="pri">{prio_pill(x["priority"])}</div></div>' for x in recs)
    dials_html = "".join(dial(d["score"], 62, DIAL_COLORS[i % len(DIAL_COLORS)], 6, label=d["label"], font=19) for i, d in enumerate(r["dials"]))
    exec_html = f'<div class="exec">{e(r["executive_summary"])}</div>' if r.get("executive_summary") else ""
    sections = "".join(render_section(s, i) for i, s in enumerate(r["sections"])) if r["type"] != "crawl" else ""
    crawl = render_crawl(r) if r.get("crawl_issues") else ""
    body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{e(r['title'])}</title><style>{CSS}</style></head><body><div class="page">
{header}
<h1>{e(r['title'])}</h1>
<p class="intro">{e(r['intro'])}</p>
{exec_html}
<div class="bar">Audit Results</div>
<div class="results"><div class="main">{dial(r['overall'], 120, score_color(r['overall']), 9, font=34)}<div class="verdict">{e(r['verdict'])}</div><div style="margin-top:6px">{pill(f"Recommendations: {len(recs)}", "pink")}</div><div class="muted" style="margin-top:4px">Grade {e(r['grade'])} · {e(r['generated'])}</div></div>{shot_html}</div>
<div class="dials"><div class="dialrow">{dials_html}</div>{radar(r['dials'])}</div>
<div class="bar">Recommendations</div>
<div class="recs">{recs_html or '<p class="muted">No recommendations. Great work!</p>'}</div>
{render_action_plan(r)}
{sections}
{crawl}
<div class="footer">Report generated {e(r['generated'])} for {e(r['url'])}{' · Domain Rating by Ahrefs' if any(c.get('extra', {}).get('metrics') and any('Ahrefs' in (m.get('source') or '') for m in c['extra']['metrics']) for s in r['sections'] for c in s['checks']) else ''}</div>
</div></body></html>"""
    out = run_dir / "report.html"
    out.write_text(body)
    return out


def to_pdf(html_path: Path, pdf_path: Path) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(html_path.resolve().as_uri(), wait_until="load")
        pg.wait_for_timeout(1200)
        pg.emulate_media(media="print")
        pg.pdf(path=str(pdf_path), format="A4", print_background=True, margin={"top": "12mm", "bottom": "14mm", "left": "10mm", "right": "10mm"}, prefer_css_page_size=True)
        b.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--white-label", default=None)
    ap.add_argument("--name", default=None, help="Base filename for outputs (default report)")
    a = ap.parse_args()
    run = Path(a.run_dir).expanduser()
    html_path = render(run, a.white_label)
    if a.name:
        target = run / f"{a.name}.html"
        html_path.rename(target)
        html_path = target
    print(f"[render] HTML -> {html_path}")
    if not a.no_pdf:
        pdf = html_path.with_suffix(".pdf")
        to_pdf(html_path, pdf)
        print(f"[render] PDF  -> {pdf}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
