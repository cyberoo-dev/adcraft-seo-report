---
name: seo-report
description: "Generate branded, SEOptimer-style SEO / GEO / AEO / site-crawl audit reports (HTML + PDF) for any website, on the Claude plan with free data sources. Use for: seo report, geo report, aeo report, audit report, client audit, seoptimer replacement, crawl report, backlink and ranking snapshot. Invoked as /seo-report <url>."
user-invocable: true
argument-hint: "<url> [seo|geo|aeo|local|gbp|crawl|all] [--plan] [--summary] [--white-label \"Client\"] [--crawl N] [--location \"City, State, Country\"]"
---

# Adcraft SEO Report

Produces client-ready audit PDFs that look like the SEOptimer reports in `~/Downloads/SEOptimer Reports`,
using the deterministic scripts in this skill plus your own judgement for the content-quality checks,
prompt visibility and the action plan. The claude-seo plugin supplies the Python runtime and Common Crawl
data; never modify that plugin.

All scripts run through `~/.claude/skills/seo-report/run.sh <script> ...` (never a bare python).
Keys live in `~/.config/adcraft-seo/keys.env`. Agency details and defaults are in `config.json`.
Output goes to `~/adcraft-seo-reports/<domain>/<YYYY-MM-DD>/`.

## Step 0: Options

Parse `$ARGUMENTS`. The first token is the URL (required; if missing, ask for it). Then use **one**
AskUserQuestion round for anything not already given on the command line:

1. **Report type** (multiSelect): SEO Audit (Recommended) / GEO Audit / AEO Audit / Local SEO Audit / Google Business Profile Audit / Site Crawl & Issues
2. **Scope**: Homepage only (Recommended) / Crawl up to 50 pages / Crawl up to 200 pages
3. **Extras** (multiSelect): Action plan / Executive summary / White label (no Adcraft branding) / Deep analysis via claude-seo agents
4. **Keywords & prompts**: Let Claude choose (Recommended) / I'll provide them

Skip the question entirely when the command line already settles every choice (e.g. `all --plan`).
If white label was chosen and no client name was given, ask for it in the same round via a follow-up only if needed.

## Step 1: Collect (phase 1, no external APIs)

```
RUN=~/adcraft-seo-reports/<domain>/<YYYY-MM-DD>
~/.claude/skills/seo-report/run.sh collect.py <url> --out $RUN --skip-external [--crawl N] [--location "..."]
```

Takes 30 to 90 seconds. Then read `$RUN/data.json` (use `python3 -c` or `jq` to pull only what you need:
`page.title`, `page.meta_description`, `page.headings`, `page.keywords`, `page.phrases`, `page.raw_text_excerpt`,
`page.local_schema_block`, `brand`, `location`). Do not dump the whole file into context.

## Step 2: Choose keywords, prompts, brand, location

From the page content decide:
- **brand**: confirm or correct `data.brand`.
- **location**: city/state/country the business serves (schema address, footer, copy). Default is in config.json.
- **6 keywords**: realistic commercial queries a customer would type, mixing service + location
  ("web design wollongong"), the brand name ("adcraft studio"), and one broader term. Google returns 10 results
  per SerpApi search and we check two pages, so each keyword costs up to 2 of the 250 free monthly searches.
- **local keyword** (Local/GBP only): the single category phrase the business most wants to own, e.g. "marketing agency".
- **10 discovery prompts**: natural questions someone would ask an AI assistant when looking for this kind of
  business in this area, e.g. "What are the best digital marketing agencies in Wollongong for a small business?".
  Vary intent: best/recommended, specific service, comparison, budget, "who should I hire for".

If the user chose to provide them, use theirs. Tell the user the lists in one short line each.

## Step 3: Collect (phase 2, external metrics)

```
~/.claude/skills/seo-report/run.sh collect.py <url> --out $RUN --external-only \
  --brand "<brand>" --location "<location>" \
  --keywords "kw1;kw2;..." --prompts "p1;p2;..." \
  [--local --local-keyword "marketing agency"]     # only for Local SEO / GBP reports (3 extra SerpApi searches)
```

This calls Ahrefs DR, OpenPageRank, Common Crawl, PageSpeed (if key), SerpApi rankings + AI Overviews +
local pack + Reddit/YouTube citations + Google Maps listing, Wikipedia, and Gemini grounded prompts.
Anything without data is simply omitted from the report (no "not measured" rows, sections or dials). Budget:
about 15 SerpApi searches for an SEO/GEO run (6 keywords x up to 2 pages + 3 citation/listing searches) and 18
with `--local`, out of 250 free per month. Skip `--prompts` for SEO-only reports to save Gemini quota (free tier
is rate limited; the collector retries 429s automatically).
Add `--skip-cc` if Common Crawl is slow (first run downloads a large ranking file, later runs are cached).

## Step 4: Your assessments -> `$RUN/ai.json`

Write `$RUN/ai.json` with this shape (omit keys you did not do):

```json
{
  "entity_definition":   {"pass": true,  "partial": false, "evidence": "The page identifies Adcraft Studio as a Wollongong digital agency offering marketing, web design and branding."},
  "contact_transparency":{"pass": true,  "evidence": "Named contact, email, phone, street address, ABN in footer."},
  "answer_alignment":    {"pass": false, "partial": true, "evidence": "An FAQ exists but answers are one line and not self-contained."},
  "citation_readiness":  {"pass": true,  "evidence": "Pricing, review counts, dated case studies and client outcomes are stated as facts."},
  "content_structure":   {"pass": true,  "evidence": "Clear H2/H3 hierarchy, short paragraphs, service cards, numbered FAQ."},
  "content_freshness":   {"pass": true,  "evidence": "2026 copyright, blog posts dated Aug 2026, current pricing."},
  "prompt_results": {
    "claude": [{"prompt": "...", "mentioned": true, "rank": 2, "businesses": ["A", "B", "Adcraft Studio"], "answer_excerpt": "..."}]
  },
  "executive_summary": "Three to five sentences a client can read in 20 seconds.",
  "action_plan": [
    {"title": "Add alt text to the 5 portfolio images", "priority": "Low Priority", "why": "...", "steps": ["...", "..."], "effort": "30 min", "impact": "Low"}
  ]
}
```

- **Content checks** (GEO/AEO only): judge from `page.raw_text_excerpt`, headings and schema. Be concrete in
  `evidence`; it is printed in the report.
- **prompt_results.claude** (GEO/AEO only): answer each discovery prompt yourself the way you would for a
  real user, using WebSearch, and record the numbered list of businesses you would give, whether the brand
  appears, and its rank. Be honest; do not favour the client. 10 prompts = 10 searches.
- **executive_summary** and **action_plan**: only if selected. Build the plan from `report.json`
  recommendations after Step 5's first build (run build once, read `recommendations`, then write the plan and
  build again). Order by impact, 5 to 10 items, plain client language, concrete steps.
- **Deep analysis** (only if selected): run the claude-seo plugin's `/seo page <url>` (SEO) or `/seo geo <url>`
  (GEO/AEO) inline, then fold its Critical and High findings into the action plan as extra items with the
  plugin's observation as the `why`. Do not paste the plugin's full markdown into the report.

## Step 5: Build and render

For each selected type:

```
~/.claude/skills/seo-report/run.sh build_report.py $RUN --type seo|geo|aeo|local|gbp|crawl [--no-action-plan]
~/.claude/skills/seo-report/run.sh render_report.py $RUN --name <type>-report [--white-label "Client Name"]
```

`build_report.py` writes `$RUN/report.json` (overwritten per type; render immediately after each build).
`render_report.py` writes `<type>-report.html` and `<type>-report.pdf` in `$RUN`. Crawl reports need `--crawl N`
in Step 1. Then `open $RUN/<type>-report.pdf` for the user.

## Step 6: Report back

Give the user, in under 120 words: the PDF paths, overall score and grade per report, the top three
recommendations, and anything that was not measured because a key was missing (name the key). Do not
paste the report contents.

## Notes and gotchas

- macOS fork-safety: requests must never consult the system proxy (handled in collect.py). If Playwright or
  dig ever "closes while reading from the driver", that is the cause.
- Screenshots use a load-event wait, not network-idle, because animated sites never go idle.
- Scores: category = weighted pass share (warn counts half). Overall = weighted mean (SEO: On-Page 30,
  GEO 15, Links 20, Usability 15, Performance 20; GEO: Accessibility 25, Content 25, Prompts 20, Citations 10,
  On-Page 20). Grades map 95=A+, 90=A, 85=A-, 80=B+ ... 40=D-, else F.
- Links score is only meaningful when Ahrefs or OpenPageRank keys are present.
- To test all data sources at once: `run.sh check_keys.py <domain>`.
- To change agency branding, edit `config.json` and `assets/adcraft-logo.svg`.
- Source of truth is the private GitHub repo `cyberoo-dev/adcraft-seo-report`. `run.sh` fast-forward pulls it
  quietly once a day, so both Macs stay current. After editing the skill here, commit and push:
  `git -C ~/.claude/skills/seo-report add -A && git -C ~/.claude/skills/seo-report commit -m "..." && git -C ~/.claude/skills/seo-report push`.
- New Mac: `curl -fsSL https://raw.githubusercontent.com/cyberoo-dev/adcraft-seo-report/main/install.sh | bash`
  (needs GitHub access to the private repo, e.g. `gh auth login` first), then copy `~/.config/adcraft-seo/keys.env` across.
- Local SEO and GBP reports need the Google Business Profile's website field to match the audited domain; otherwise
  the listing is reported as unverified and the GBP audit says so.
