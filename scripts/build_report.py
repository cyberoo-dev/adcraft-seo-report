#!/usr/bin/env python3
"""Turn data.json (+ optional ai.json written by Claude) into report.json: scored sections,
checks with pass/fail wording, recommendations, and grades. Deterministic.

Usage: build_report.py <run_dir> --type seo|geo|aeo|crawl [--no-action-plan]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import read_json, write_json, load_config  # noqa: E402

PASS, FAIL, WARN, INFO = "pass", "fail", "warn", "info"
HIGH, MED, LOW = "High Priority", "Medium Priority", "Low Priority"


def fmt_mb(b: int | float | None) -> str:
    return f"{(b or 0) / 1_000_000:.2f}MB"


def grade(score: float) -> str:
    for cut, g in ((95, "A+"), (90, "A"), (85, "A-"), (80, "B+"), (75, "B"), (70, "B-"), (65, "C+"), (60, "C"),
                   (55, "C-"), (50, "D+"), (45, "D"), (40, "D-")):
        if score >= cut:
            return g
    return "F"


def verdict(score: float, noun: str) -> tuple[str, str]:
    if score >= 85:
        return f"Your {noun} is very good!", "very good"
    if score >= 70:
        return f"Your {noun} is good", "good"
    if score >= 55:
        return f"Your {noun} could be better", "could be better"
    return f"Your {noun} needs work", "needs work"


class Check:
    def __init__(self, cid, title, status, summary, what="", how="", details=None, priority=LOW, weight=1,
                 rec_title=None, kind="row", extra=None, hide=False):
        self.d = {"id": cid, "title": title, "status": status, "summary": summary, "what": what, "how": how,
                  "details": details or [], "priority": priority, "weight": weight if status != INFO else 0,
                  "rec_title": rec_title, "kind": kind, "extra": extra or {}, "hide": hide}


# --------------------------------------------------------------------------- explanation copy

WHAT = {
    "title": "The Title Tag tells users and search engines what a page is about and which keywords it should rank for. It appears in the browser tab and as the headline of your search result, and is one of the most influential and easiest on-page factors to improve.",
    "meta": "The Meta Description explains in more detail what a page is about. Search engines often use it as the text snippet in results, so it influences both relevance signals and click-through rate.",
    "serp": "The SERP snippet shows how your page may appear in a Google result. The page Title, URL and Meta Description are the main components, although search engines increasingly rewrite snippets to match the query.",
    "hreflang": "Hreflang is an HTML attribute that declares the language and geographic targeting of a page and lists its alternative versions. It only matters for sites with multiple language or regional editions.",
    "lang": "The Lang attribute declares the intended language of a page to browsers and search engines, which can be used to return language-specific results.",
    "h1": "The H1 header is one of the strongest signals of a page's topic. It normally appears as the largest visible heading on the page.",
    "h2h6": "H2 to H6 headers organise page content and signal the longer-tail topics a page should rank for.",
    "kw": "A page should target a consistent set of keywords or phrases, used naturally across the Title, Meta Description, headings and body text. This check shows the terms that appear most often across those elements.",
    "content": "Studies show a relationship between the amount of content on a page and its ranking potential. Content should also be relevant, keyword-rich and readable. We measure visible text at load time.",
    "alt": "Alt text describes an image when it cannot be displayed and tells search engines what the image shows. Image SEO is an overlooked source of traffic and backlinks.",
    "canonical": "The Canonical tag tells search engines the primary URL of a page. It prevents duplicate-content problems from parameters, www and non-www versions.",
    "noindex": "A page can only rank if search engines are allowed to index it. A Noindex tag or header tells them to ignore the page. These are sometimes left over from staging or templates by mistake.",
    "ssl": "SSL encrypts data between your website and its visitors. Using HTTPS everywhere is a modern standard and a confirmed ranking signal.",
    "https_redirect": "If SSL is enabled, the site should force HTTPS by redirecting insecure HTTP requests. Otherwise users and search engines may keep using the insecure version, which can dilute ranking signals.",
    "robots": "Robots.txt gives crawlers instructions on which parts of your site to access. It is usually the first file a search engine bot reads.",
    "robots_block": "Robots.txt rules can intentionally or accidentally block search engines from important pages, for example rules left over from a staging site.",
    "sitemap": "An XML Sitemap lists the pages available for crawling, with update times and priorities, giving every page the best chance of being indexed. It should be referenced in robots.txt.",
    "analytics": "Web analytics tools such as Google Analytics let you measure website performance and understand visitor behaviour.",
    "schema": "Schema.org structured data lets search engines interpret page content more precisely and enable rich results such as business details, reviews and products.",
    "render": "LLMs and AI crawlers predominantly read the raw HTML of a page rather than the version produced after JavaScript runs, because rendering at scale is slow and expensive. Important content that only appears after rendering may be missed.",
    "llms": "llms.txt is a proposed standard file that gives large language models a concise, structured overview of a site's content and where to find its most useful documents.",
    "ai_bots": "Generative engines such as ChatGPT, Google AI Overviews, Perplexity and Claude use their own crawlers to read and cite web content. If robots.txt blocks those user agents, your pages cannot be surfaced or cited in AI answers.",
    "identity": "Organisation or Person schema tells search engines and LLMs who you are, so they can confidently answer brand queries, recommend your services and avoid confusing you with similarly named businesses.",
    "entity": "AI systems need to identify clearly which business, organisation or person a page represents before they will attribute, trust or recommend it.",
    "contact": "Explicit business details such as legal name, address, phone, email and registration numbers build trust and help AI systems verify and cite the business.",
    "answers": "Content written in explicit question-and-answer form maps directly onto the questions people ask AI assistants, making it far easier to surface and cite.",
    "citable": "Self-contained facts, statistics, quotes and clear claims are the kind of snippets LLMs prefer to quote when answering questions.",
    "structure": "Well-structured, scannable content with clear headings, lists, tables and short paragraphs is easier for LLMs to parse, chunk and reuse.",
    "fresh": "Generative engines favour content that appears current. Visible dates, recent articles and up-to-date details make a page more likely to be surfaced and cited.",
    "backlinks": "Backlinks are links from other websites to yours. Search engines treat them as a strong signal of authority. More links from authoritative, relevant sites improve ranking ability.",
    "linkstructure": "On-page link structure covers how a page links to internal and external pages and whether external links pass authority. A healthy page has a strong proportion of internal links.",
    "friendly": "URLs should be short and human readable, with words separated by hyphens and without file names, parameters, special characters or deep folder chains.",
    "devices": "Most traffic now comes from mobile devices. A page should render correctly across desktop, tablet and phone screen sizes and adapt smoothly between them.",
    "cwv": "Core Web Vitals are Google's user-experience metrics measuring loading (LCP), interactivity (INP) and visual stability (CLS), gathered from real Chrome users. They are a ranking factor.",
    "viewport": "The Viewport meta tag tells browsers how to scale a page to the device's screen. Without it, mobile pages appear zoomed out and hard to read.",
    "flash": "Flash is an obsolete technology that is unsupported on mobile devices and unreadable by search engines. Modern HTML, CSS and JavaScript replace it.",
    "iframes": "iFrames embed other pages inside a page. They can complicate mobile navigation and have historically been harder to index, although tools such as Google Tag Manager still rely on them.",
    "favicon": "A favicon is the small icon shown in browser tabs and bookmarks. It helps users find your page and adds legitimacy and brand recognition, including in mobile search results.",
    "email": "Email addresses shown in plain text on a page are easily harvested by bots and added to spam lists.",
    "speed": "Page load speed is the time a page takes to fully load in a visitor's browser. It affects user experience, bounce rate, conversions and rankings. It depends on server, network, page size and code quality.",
    "size": "Download page size is the total data a browser must download to display a page, including HTML, CSS, JavaScript and images. It is one of the biggest contributors to load speed. Under 5MB is a good target.",
    "compression": "Modern web servers compress files during transfer using GZIP, Deflate or Brotli, often dramatically reducing download size. It is usually enabled by default but can be partially configured.",
    "resources": "Every file a browser must retrieve is another network request with connection overhead. Consolidating and removing unnecessary files improves load time.",
    "amp": "AMP (Accelerated Mobile Pages) was a Google initiative for faster mobile pages. It has been widely deprecated and is no longer a ranking requirement.",
    "jserrors": "JavaScript errors can interrupt page execution and break other functionality. They should be examined to understand their cause and impact.",
    "http2": "HTTP/2 and HTTP/3 are newer protocol versions with significant performance improvements over HTTP/1.1. Older configurations may not use them even when the server supports them.",
    "deprecated": "HTML has removed older tags over time. Deprecated tags may not render as expected and can break functionality in modern browsers.",
    "inline": "Inline styles embed presentation inside individual HTML elements. Best practice separates styling into CSS files, which improves maintainability and can improve load performance.",
    "social_link": "Creating social profiles and linking to them from your website builds trust and provides more channels to nurture customer relationships.",
    "og": "Open Graph tags control the title, description and image shown when a page is shared on Facebook and other platforms. Without them, platforms guess which content to display.",
    "pixel": "The Facebook Pixel captures visitor data so you can retarget visitors and build lookalike audiences for Meta advertising.",
    "xcards": "X Cards, like Open Graph, control what is shown when a page is shared on X.",
    "youtube_activity": "An active YouTube channel with a healthy subscriber base is a strong brand signal and one of the sources AI engines cite most.",
    "local_schema": "Local Business schema tells search engines which business a site represents, including address, phone, opening hours and reviews, so it can rank in local results.",
    "gbp": "A Google Business Profile is the listing that appears in Google Maps and local searches. It contains name, location, contact details, hours, ratings and reviews and is essential for local visibility.",
    "gbp_complete": "The Name, Address and Phone (NAP) on your Google Business Profile must be complete and consistent with your website. Google uses them to match citations of your business across the web.",
    "reviews": "Google reviews and ratings directly affect customer trust and are a ranking signal for local search results.",
    "dmarc": "DMARC is a DNS record that helps prevent email spoofing from your domain. Major mail providers increasingly require it, and it affects deliverability.",
    "spf": "An SPF record identifies the mail servers permitted to send email on behalf of your domain and helps combat spoofing.",
    "wikipedia": "Wikipedia is one of the most heavily cited sources by LLMs, and ChatGPT in particular draws heavily on it. References from Wikipedia establish your business as a recognised entity.",
    "reddit": "Reddit discussions are among the most frequently cited sources for Perplexity and Google AI Overviews. Genuine mentions in relevant threads help your business appear in the community content AI engines draw on.",
    "youtube_cite": "YouTube videos are heavily cited by AI engines, and Google AI Overviews increasingly surface video directly. References in titles, descriptions and transcripts help your business appear in the content AI answers are built from.",
    "rankings": "The keywords a site ranks for, and the positions it holds, determine how much organic traffic it can attract. The top three positions receive the majority of clicks.",
    "aio": "Google AI Overviews appear above traditional results for many queries and cite a small number of sources. Being one of those sources is now a major visibility lever.",
    "prompts": "Prompt visibility measures how often, and how prominently, LLMs recommend your business when answering real discovery questions in your space.",
}

HOW = {
    "title": "Set a keyword-rich Title between 50 and 60 characters. Most CMS platforms expose this in page settings.",
    "meta": "Write an engaging Meta Description between 120 and 160 characters using the page's target phrases. This is usually editable in your CMS.",
    "serp": "Craft the Title, URL and Meta Description so the snippet is enticing and accurately represents the page.",
    "hreflang": "If you publish the same page in multiple languages or regions, add hreflang links for each version. Otherwise no action is needed.",
    "lang": "Add a lang attribute to the html tag of every page.",
    "h1": "Add one, and only one, H1 near the top of the page containing the primary keyword.",
    "h2h6": "Use at least two other heading levels, such as H2 and H3, with relevant keywords, to structure the content.",
    "kw": "If the identified terms do not match your target keywords, revise the page content and tags to feature them consistently without stuffing.",
    "content": "Aim for at least 500 words of relevant, readable content on pages that should rank. Contact-style pages are an exception.",
    "alt": "Add descriptive, keyword-relevant alt text to meaningful images, particularly those with ranking potential. Decorative images can use empty alt attributes.",
    "canonical": "Specify the preferred URL of each page with a canonical link. Most CMS platforms manage this automatically.",
    "noindex": "If the page should rank, remove the Noindex tag or header. Check your CMS for a 'discourage search engines' or 'hide from search' setting.",
    "ssl": "Enable SSL through your host or CMS and confirm the site loads at an https:// address.",
    "https_redirect": "Configure a permanent redirect from HTTP to HTTPS in your hosting control panel, CMS or server configuration.",
    "robots": "Create a robots.txt file at the site root. Most CMS platforms and hosts can generate one.",
    "robots_block": "Review Disallow rules and remove any that block search engines from pages that should rank.",
    "sitemap": "Generate an XML Sitemap with your CMS or a utility, publish it at the site root and reference it in robots.txt.",
    "analytics": "Install an analytics tool such as Google Analytics 4 via a tag manager, plugin or directly in the page code.",
    "schema": "Add relevant Schema.org JSON-LD such as Organization, LocalBusiness, Article or Product using your CMS, a plugin or a schema generator.",
    "render": "Ensure important content is present in the raw HTML and minimise plugins and scripts that inject content dynamically. Server-side rendering or static generation solves this for JavaScript frameworks.",
    "llms": "Publish a Markdown llms.txt file at the site root summarising the business and linking to key pages. Free generators and CMS plugins exist.",
    "ai_bots": "Review robots.txt for Disallow rules targeting AI crawler user agents such as GPTBot, Google-Extended, ClaudeBot, PerplexityBot and CCBot, and remove them if you want to appear in AI answers.",
    "identity": "Add Organization or Person schema with name, url, logo, sameAs links to social profiles and contact details, via your CMS, a plugin or a schema generator.",
    "entity": "Make the business name and what it does prominent and unambiguous through clear headings, an intro or about section and consistent naming.",
    "contact": "Publish legal name, address, phone, email and registration numbers such as an ABN, typically in the footer and on a dedicated contact page.",
    "answers": "Add an FAQ section or structure key content as clear questions with concise, self-contained answers beneath them.",
    "citable": "Include concrete facts, statistics and quotable statements written as clear self-contained sentences that still make sense when cited alone.",
    "structure": "Break content into a clear heading hierarchy with sub-headings, lists, tables and short paragraphs rather than dense blocks of text.",
    "fresh": "Show publish or last-updated dates, reference the current year and keep details such as prices, team and events up to date.",
    "backlinks": "Adopt a link-building strategy: relevant directories, partner and supplier links, PR and guest content, and lead-magnet content that others want to reference.",
    "linkstructure": "Keep most links internal, and use nofollow on external links to lower-quality sites where you do not intend to pass value.",
    "friendly": "Shorten URLs, use hyphenated words, and remove parameters, encoded characters and unnecessary folder levels. Redirect old URLs when changing them.",
    "devices": "Design and test the site responsively across common desktop, tablet and phone resolutions.",
    "cwv": "Follow the recommendations in Google's PageSpeed Insights report for this page, focusing on the largest image, render-blocking scripts and layout shifts.",
    "viewport": "Add a single meta viewport tag with width=device-width, initial-scale=1 to the page head.",
    "flash": "Replace any Flash content with modern HTML5 equivalents.",
    "iframes": "Remove iFrames that do not serve a critical purpose, or replace them with native content. Tag manager iframes can usually stay.",
    "favicon": "Create a favicon with an online generator or designer and add it to the site or CMS settings.",
    "email": "Replace plain-text email addresses with a contact form, an image, or obfuscated text.",
    "speed": "Reduce total file size, optimise images, defer non-critical scripts and consider a CDN or better hosting.",
    "size": "Compress and resize images, use modern formats such as WebP or AVIF, minify code and remove unused files.",
    "compression": "Enable GZIP or Brotli compression for all text file types on the web server or CDN.",
    "resources": "Combine and minify scripts and styles, lazy-load below-the-fold images and remove unused third-party scripts.",
    "amp": "No action is required. AMP is optional and largely superseded by good Core Web Vitals.",
    "jserrors": "Investigate the errors in the browser console and fix or remove the failing scripts.",
    "http2": "Ask your host or CDN to enable HTTP/2 or HTTP/3. Cloudflare and most modern hosts support it by default.",
    "deprecated": "Replace deprecated tags with modern HTML and CSS equivalents, or update the theme and libraries in use.",
    "inline": "Move inline styles into CSS files where practical. Some are generated by animation libraries and can be tolerated.",
    "social_link": "Create the profile and link it from the website footer or header.",
    "og": "Define og:title, og:description, og:image and og:url in the page head. Most SEO plugins generate them automatically.",
    "pixel": "Install the Facebook Pixel via Meta Business Suite, a tag manager or your CMS if you intend to run Meta advertising.",
    "xcards": "Add twitter:card, twitter:title, twitter:description and twitter:image tags to the page head.",
    "youtube_activity": "Publish helpful videos regularly, reference your website in titles and descriptions, and promote the channel from your site and social profiles.",
    "local_schema": "Add LocalBusiness schema, or a more specific subtype, with address, phone, opening hours, geo coordinates and sameAs links.",
    "gbp": "Create or claim your Google Business Profile and make sure its website field matches this domain exactly.",
    "gbp_complete": "Review the profile and complete every field: category, address, phone, website, hours, services, photos and description.",
    "reviews": "Ask customers for reviews systematically, respond to every review, and address negative feedback promptly.",
    "dmarc": "Publish a DMARC TXT record at _dmarc.yourdomain, starting with p=none and tightening to quarantine or reject once reports are clean.",
    "spf": "Publish an SPF TXT record listing every service that sends email for the domain, ending with ~all or -all.",
    "wikipedia": "You cannot add promotional links to Wikipedia, but you can earn citations by being a notable, verifiable source with well-referenced coverage elsewhere.",
    "reddit": "Participate authentically in subreddits relevant to your industry: answer questions and share useful expertise without overt self-promotion.",
    "youtube_cite": "Publish helpful videos that reference the website in title and description, and encourage reviews, tutorials and mentions from other creators.",
    "rankings": "Target realistic keywords with dedicated, well-optimised pages and build authority through content and links to move them onto page one.",
    "aio": "Create clear, well-structured answers to the questions behind your target keywords, with supporting facts, so your page is chosen as a cited source.",
    "prompts": "Build clearer, more authoritative content about who you are and what you offer, earn third-party mentions and reviews, and keep structured data consistent so AI tools recommend you more often.",
}


# --------------------------------------------------------------------------- check builders


def onpage_checks(d: dict, geo_variant: bool = False) -> list[Check]:
    p = d["page"]
    c: list[Check] = []
    tl = p["title_length"]
    if not p["title"]:
        c.append(Check("title", "Title Tag", FAIL, "Your page is missing a Title Tag.", WHAT["title"], HOW["title"], priority=HIGH, weight=3, rec_title="Add a Title Tag"))
    elif 50 <= tl <= 60:
        c.append(Check("title", "Title Tag", PASS, "You have a Title Tag of optimal length (between 50 and 60 characters).", WHAT["title"], HOW["title"], [p["title"], f"Length : {tl}"], weight=3))
    elif tl < 50:
        c.append(Check("title", "Title Tag", WARN, "Your Title Tag is shorter than the optimal 50 to 60 characters.", WHAT["title"], HOW["title"], [p["title"], f"Length : {tl}"], priority=MED, weight=3, rec_title="Lengthen your Title Tag"))
    else:
        c.append(Check("title", "Title Tag", WARN, "Your Title Tag is longer than the optimal 50 to 60 characters and may be truncated in results.", WHAT["title"], HOW["title"], [p["title"], f"Length : {tl}"], priority=MED, weight=3, rec_title="Shorten your Title Tag"))
    ml = p["meta_description_length"]
    if not p["meta_description"]:
        c.append(Check("meta", "Meta Description Tag", FAIL, "Your page is missing a Meta Description.", WHAT["meta"], HOW["meta"], priority=HIGH, weight=3, rec_title="Add a Meta Description"))
    elif 120 <= ml <= 160:
        c.append(Check("meta", "Meta Description Tag", PASS, "Your page has a Meta Description of optimal length (between 120 and 160 characters).", WHAT["meta"], HOW["meta"], [p["meta_description"], f"Length : {ml}"], weight=3))
    else:
        c.append(Check("meta", "Meta Description Tag", WARN, f"Your Meta Description is {'shorter' if ml < 120 else 'longer'} than the optimal 120 to 160 characters.", WHAT["meta"], HOW["meta"], [p["meta_description"], f"Length : {ml}"], priority=MED, weight=3, rec_title="Adjust your Meta Description length"))
    if not geo_variant:
        c.append(Check("serp", "SERP Snippet Preview", INFO, "This illustrates how your page may appear in Search Results. Search engines increasingly generate this content dynamically.", WHAT["serp"], HOW["serp"], kind="serp",
                       extra={"brand": d["brand"], "url": d["url"], "title": p["title"], "description": p["meta_description"], "favicon": d.get("favicon", {}).get("href")}))
        if p["hreflang"]:
            c.append(Check("hreflang", "Hreflang Usage", PASS, "Your page is using Hreflang attributes.", WHAT["hreflang"], HOW["hreflang"], [f"{h['lang']}: {h['href']}" for h in p["hreflang"][:8]], weight=0))
        else:
            c.append(Check("hreflang", "Hreflang Usage", INFO, "Your page is not making use of Hreflang attributes.", WHAT["hreflang"], HOW["hreflang"]))
        if p["lang"]:
            c.append(Check("lang", "Language", PASS, "Your page is using the Lang Attribute.", WHAT["lang"], HOW["lang"], [f"Declared: {lang_name(p['lang'])}"]))
        else:
            c.append(Check("lang", "Language", FAIL, "Your page is not using the Lang Attribute.", WHAT["lang"], HOW["lang"], priority=LOW, rec_title="Add a Lang Attribute"))
    h1 = p["headings"]["h1"]
    if len(h1) == 1:
        c.append(Check("h1", "H1 Header Tag Usage", PASS, "Your page has a H1 Tag.", WHAT["h1"], HOW["h1"], weight=2, kind="tagtable", extra={"rows": [["H1", h1[0]]]}))
    elif not h1:
        c.append(Check("h1", "H1 Header Tag Usage", FAIL, "Your page is missing a H1 Tag.", WHAT["h1"], HOW["h1"], priority=HIGH, weight=2, rec_title="Add a H1 Header Tag"))
    else:
        c.append(Check("h1", "H1 Header Tag Usage", WARN, f"Your page has {len(h1)} H1 Tags. Only one is recommended.", WHAT["h1"], HOW["h1"], priority=LOW, weight=2, rec_title="Use a single H1 Header Tag", kind="tagtable", extra={"rows": [["H1", x] for x in h1[:6]]}))
    if not geo_variant:
        counts = p["heading_counts"]
        levels = sum(1 for k in ("h2", "h3", "h4", "h5", "h6") if counts.get(k))
        rows = [[k.upper(), v] for k, v in sorted(p["headings"].items()) if k != "h1" for v in v[:30]][:40]
        freq = [[k.upper(), counts.get(k, 0)] for k in ("h2", "h3", "h4", "h5", "h6")]
        if levels >= 2:
            c.append(Check("h2h6", "H2-H6 Header Tag Usage", PASS, "Your page is making use of multiple levels of Header Tags.", WHAT["h2h6"], HOW["h2h6"], kind="headings", extra={"freq": freq, "rows": rows}))
        else:
            c.append(Check("h2h6", "H2-H6 Header Tag Usage", WARN, "Your page is using few Header Tag levels.", WHAT["h2h6"], HOW["h2h6"], priority=LOW, rec_title="Use more Header Tag levels", kind="headings", extra={"freq": freq, "rows": rows}))
        kws, phr = p["keywords"][:8], p["phrases"][:8]
        consistent = sum(1 for k in kws[:5] if k["title"] or k["meta"] or k["headings"]) >= 3
        c.append(Check("kw", "Keyword Consistency", PASS if consistent else WARN,
                       "Your page's main keywords are well distributed across the important HTML Tags." if consistent else "Your page's main keywords are not distributed consistently across the important HTML Tags.",
                       WHAT["kw"], HOW["kw"], priority=MED, rec_title="Improve keyword consistency", kind="keywords", extra={"keywords": kws, "phrases": phr}))
        wc = p["word_count"]
        if wc >= 500:
            c.append(Check("content", "Amount of Content", PASS, "Your page has a good level of textual content, which will assist in its ranking potential.", WHAT["content"], HOW["content"], [f"Word Count: {wc}"], weight=2))
        else:
            c.append(Check("content", "Amount of Content", WARN if wc >= 250 else FAIL, "Your page has a low volume of text content, which search engines may interpret as thin content.", WHAT["content"], HOW["content"], [f"Word Count: {wc}"], priority=MED, weight=2, rec_title="Increase the amount of content"))
    miss = p["images_missing_alt"]
    if not miss:
        c.append(Check("alt", "Image Alt Attributes", PASS, "All images on your page have Alt Attributes.", WHAT["alt"], HOW["alt"], [f"We found {p['images_total']} images on your page."]))
    else:
        c.append(Check("alt", "Image Alt Attributes", WARN if len(miss) <= 5 else FAIL, "You have images on your page that are missing Alt Attributes.", WHAT["alt"], HOW["alt"],
                       [f"We found {p['images_total']} images on your page and {len(miss)} of them are missing the attribute."], priority=LOW if len(miss) <= 5 else MED, rec_title="Add Alt Attributes to all images", kind="imagelist", extra={"images": miss[:10]}))
    if p["canonical"]:
        c.append(Check("canonical", "Canonical Tag", PASS, "Your page is using the Canonical Tag.", WHAT["canonical"], HOW["canonical"], [p["canonical"]]))
    else:
        c.append(Check("canonical", "Canonical Tag", WARN, "Your page is not using the Canonical Tag.", WHAT["canonical"], HOW["canonical"], priority=LOW, rec_title="Add a Canonical Tag"))
    c.append(Check("noindex", "Noindex Tag Test", FAIL if p["noindex_tag"] else PASS,
                   "Your page is using the Noindex Tag which prevents indexing." if p["noindex_tag"] else "Your page is not using the Noindex Tag which prevents indexing.",
                   WHAT["noindex"], HOW["noindex"], priority=HIGH, weight=3, rec_title="Remove the Noindex Tag"))
    if not geo_variant:
        c.append(Check("noindex_h", "Noindex Header Test", FAIL if d["noindex_header"] else PASS,
                       "Your page is using the Noindex Header which prevents indexing." if d["noindex_header"] else "Your page is not using the Noindex Header which prevents indexing.",
                       WHAT["noindex"], HOW["noindex"], priority=HIGH, weight=3, rec_title="Remove the Noindex Header"))
        hs = d["https"]
        c.append(Check("ssl", "SSL Enabled", PASS if hs["ssl"] else FAIL, "Your website has SSL enabled." if hs["ssl"] else "Your website does not appear to have SSL enabled.", WHAT["ssl"], HOW["ssl"], priority=HIGH, weight=3, rec_title="Enable SSL"))
        c.append(Check("https_redirect", "HTTPS Redirect", PASS if hs["http_redirects_to_https"] else FAIL,
                       "Your page successfully redirects to a HTTPS (SSL secure) version." if hs["http_redirects_to_https"] else "Your page does not redirect HTTP requests to the HTTPS version.",
                       WHAT["https_redirect"], HOW["https_redirect"], priority=HIGH, weight=2, rec_title="Redirect HTTP to HTTPS"))
        rb = d["robots"]
        c.append(Check("robots", "Robots.txt", PASS if rb["present"] else FAIL, "Your website appears to have a robots.txt file." if rb["present"] else "Your website does not appear to have a robots.txt file.", WHAT["robots"], HOW["robots"], [rb["url"]] if rb["present"] else [], priority=LOW, rec_title="Add a robots.txt file"))
    rb = d["robots"]
    blocked = rb["blocked_search_bots"] or (["all crawlers"] if rb["blocks_all"] else [])
    c.append(Check("robots_block", "Search Engines Blocked by Robots.txt", FAIL if blocked else PASS,
                   "Your page is blocked for some major search engines in your robots.txt." if blocked else "Your page is crawlable by the major search engines.",
                   WHAT["robots_block"], HOW["robots_block"], [f"Blocked: {', '.join(blocked)}"] if blocked else ["No major search engines are blocked in your robots.txt."], priority=HIGH, weight=3, rec_title="Unblock search engines in robots.txt"))
    if not geo_variant:
        sm = d["sitemap"]
        c.append(Check("sitemap", "XML Sitemaps", PASS if sm["present"] else FAIL, "Your website appears to have an XML Sitemap." if sm["present"] else "Your website does not appear to have an XML Sitemap.",
                       WHAT["sitemap"], HOW["sitemap"], ([sm["url"], f"{sm['url_count']} URLs listed" + (f" across {sm['child_sitemaps']} child sitemaps (first 5 read)" if sm["child_sitemaps"] else "")] if sm["present"] else []), priority=MED, weight=2, rec_title="Add an XML Sitemap"))
        an = p["analytics"]
        c.append(Check("analytics", "Analytics", PASS if an else FAIL, "Your page is using an analytics tool." if an else "Your page does not appear to be using an analytics tool.", WHAT["analytics"], HOW["analytics"], an, priority=MED, rec_title="Install an analytics tool"))
    if p["schema_jsonld"]:
        c.append(Check("schema", "Schema.org Structured Data", PASS, "You are using JSON-LD Schema on your page.", WHAT["schema"], HOW["schema"], p["schema_all_types"][:12], weight=2))
    elif p["schema_microdata"]:
        c.append(Check("schema", "Schema.org Structured Data", PASS, "You are using Microdata Schema on your page.", WHAT["schema"], HOW["schema"], weight=2))
    else:
        c.append(Check("schema", "Schema.org Structured Data", FAIL, "No Schema.org structured data was found on your page.", WHAT["schema"], HOW["schema"], priority=MED, weight=2, rec_title="Add Schema.org Structured Data"))
    return c


def lang_name(code: str) -> str:
    return {"en": "English", "en-au": "English (Australia)", "en-us": "English (US)", "en-gb": "English (UK)"}.get(code.lower(), code)


def geo_core_checks(d: dict) -> list[Check]:
    p = d["page"]
    c: list[Check] = []
    rp = p["render_pct"]
    if rp <= 10:
        c.append(Check("render", "Rendered Content (LLM Readability)", PASS, "Your page has a low level of rendering (changes to the HTML), so most content is visible to LLMs.", WHAT["render"], HOW["render"], [f"Rendering Percentage: {rp}%"], weight=2))
    else:
        c.append(Check("render", "Rendered Content (LLM Readability)", WARN if rp < 40 else FAIL, "Your page has a high level of rendering (changes to the HTML).", WHAT["render"], HOW["render"],
                       [f"Rendering Percentage: {rp}%", "Dynamically rendering a lot of page content risks important information being missed by LLMs that generally do not read this content."], priority=LOW if rp < 40 else MED, weight=2, rec_title="Reduce Rendered Content"))
    ll = d["llms_txt"]
    c.append(Check("llms", "Llms.txt", PASS if ll["present"] else WARN, "Your website appears to have a llms.txt file." if ll["present"] else "Your website does not appear to have a llms.txt file.",
                   WHAT["llms"], HOW["llms"], [ll["url"]] if ll["present"] else [], priority=LOW, rec_title="Add a llms.txt file"))
    ai = d["robots"]["blocked_ai_bots"]
    c.append(Check("ai_bots", "AI Crawlers Blocked by Robots.txt", FAIL if ai else PASS,
                   "Your robots.txt blocks some major AI crawlers from accessing your site." if ai else "Your robots.txt allows the major AI crawlers to access your site.",
                   WHAT["ai_bots"], HOW["ai_bots"], [f"Blocked: {', '.join(ai)}"] if ai else [], priority=HIGH, weight=3, rec_title="Allow AI crawlers in robots.txt"))
    idt = p["identity_schema"] or [t for t in p["schema_all_types"] if t in ("Organization", "Person")]
    c.append(Check("identity", "Identity Schema", PASS if idt else FAIL, "Organisation or Person Schema identified on the page." if idt else "No Organisation or Person Schema was identified on the page.",
                   WHAT["identity"], HOW["identity"], list(dict.fromkeys(idt))[:5], priority=MED, weight=2, rec_title="Add Organisation or Person Schema"))
    return c


def ai_assessed_checks(ai: dict | None) -> list[Check]:
    spec = [("entity_definition", "Entity Definition", "entity", "Your page clearly defines the entity it represents.", "Your page does not clearly define the entity it represents.", "Define the entity your page represents", 2),
            ("contact_transparency", "Contact Transparency", "contact", "Your page clearly provides business details and contact points.", "Your page does not clearly provide business details and contact points.", "Publish clear business and contact details", 2),
            ("answer_alignment", "Answer Alignment", "answers", "Your page includes clear question-and-answer style content.", "Your page does not include clear question-and-answer style content.", "Add question-and-answer content", 2),
            ("citation_readiness", "Citation Readiness", "citable", "Your page contains easily citable facts, quotes or statistics.", "Your page lacks easily citable facts, quotes or statistics.", "Add citable facts and statistics", 2),
            ("content_structure", "Content Structure", "structure", "Your page is well structured and easy for AI to parse.", "Your page structure makes it hard for AI to parse.", "Improve content structure", 2),
            ("content_freshness", "Content Freshness", "fresh", "Your page shows clear signals that its content is current.", "Your page lacks clear signals that its content is current.", "Add freshness signals", 1)]
    out = []
    for key, title, k, ok, bad, rec, w in spec:
        a = (ai or {}).get(key)
        if not a:
            out.append(Check(key, title, INFO, "", hide=True))
            continue
        st = PASS if a.get("pass") else (WARN if a.get("partial") else FAIL)
        out.append(Check(key, title, st, ok if st == PASS else bad, WHAT[k], HOW[k], [a.get("evidence", "")] if a.get("evidence") else [], priority=MED, weight=w, rec_title=rec))
    return out


def links_checks(d: dict) -> list[Check]:
    p, ext = d["page"], d["external"]
    c: list[Check] = []
    ah, opr, cc = ext.get("ahrefs", {}), ext.get("openpagerank", {}), ext.get("commoncrawl", {})
    dr = ah.get("domain_rating") if ah.get("available") else None
    if isinstance(dr, dict):
        dr = dr.get("domain_rating")
    row = (opr.get("rows") or [{}])[0] if opr.get("available") else {}
    opr_score = row.get("open_page_rank") or row.get("page_rank_decimal")
    ref = row.get("referring_domains")
    rank = row.get("rank")
    metrics = []
    if dr is not None:
        metrics.append({"label": "Domain Rating", "value": round(float(dr)), "max": 100, "source": "Domain Rating by Ahrefs"})
    if opr_score is not None:
        metrics.append({"label": "PageRank", "value": round(float(opr_score) * 10), "max": 100, "display": f"{float(opr_score):.1f} / 10", "source": "OpenPageRank"})
    if ref is not None:
        metrics.append({"label": "Referring Domains", "value": ref, "raw": True, "source": "OpenPageRank"})
    if not metrics and cc.get("available") and cc.get("in_rankings"):
        metrics.append({"label": "Common Crawl Rank", "value": cc.get("harmonic_centrality_rank"), "raw": True, "source": "Common Crawl web graph"})
    strength = None
    if dr is not None:
        strength = float(dr)
    elif opr_score is not None:
        strength = float(opr_score) * 10
    if strength is None:
        c.append(Check("backlinks", "Backlink Summary", INFO, "", hide=True))
    elif strength >= 40:
        c.append(Check("backlinks", "Backlink Summary", PASS, "You have a strong level of backlink activity to this website.", WHAT["backlinks"], HOW["backlinks"], weight=4, kind="metrics", extra={"metrics": metrics}))
    elif strength >= 20:
        c.append(Check("backlinks", "Backlink Summary", WARN, "You have a moderate level of backlink activity to this website.", WHAT["backlinks"], HOW["backlinks"], priority=MED, weight=4, rec_title="Build more backlinks", kind="metrics", extra={"metrics": metrics}))
    else:
        c.append(Check("backlinks", "Backlink Summary", FAIL, "You have a low level of backlink activity to this website.", WHAT["backlinks"], HOW["backlinks"], priority=HIGH, weight=4, rec_title="Build a backlink strategy", kind="metrics", extra={"metrics": metrics}))
    hist = row.get("history") or []
    if hist:
        c.append(Check("authority_trend", "Authority Trend", INFO, "Monthly PageRank history for the domain (OpenPageRank).", "", "", kind="history", extra={"history": hist[-12:]}))
    if cc.get("available"):
        if cc.get("in_rankings"):
            c.append(Check("cc", "Common Crawl Web Graph", INFO, "Your domain appears in the Common Crawl link graph, meaning other crawled sites link to it.", "Common Crawl is an open, quarterly crawl of the web. Its link graph ranks domains by how many other domains link to them.", "", [f"Harmonic centrality rank: #{cc.get('harmonic_centrality_rank'):,}", f"PageRank rank: #{cc.get('pagerank_rank'):,}", f"Hosts seen: {cc.get('n_hosts')}", f"Release: {cc.get('release')}"]))
        else:
            c.append(Check("cc", "Common Crawl Web Graph", WARN, "Your domain does not appear in the Common Crawl link graph, suggesting very few sites link to it.", "Common Crawl is an open, quarterly crawl of the web. Its link graph ranks domains by how many other domains link to them.", HOW["backlinks"], priority=MED, rec_title="Earn links from established websites"))
    ln = p["links"]
    ext_pct = round(100 * (ln["external_follow"] + ln["external_nofollow"]) / ln["total"]) if ln["total"] else 0
    nf_pct = round(100 * ln["external_nofollow"] / ln["total"]) if ln["total"] else 0
    c.append(Check("linkstructure", "On-Page Link Structure", INFO,
                   f"We found {ln['total']} total links. {ext_pct}% of your links are external links and are sending authority to other sites. {nf_pct}% of your links are nofollow links, meaning authority is not being passed to those destination pages.",
                   WHAT["linkstructure"], HOW["linkstructure"], kind="links", extra={"links": ln}))
    uf = p["unfriendly_urls"]
    if uf:
        c.append(Check("friendly", "Friendly Links", WARN, "Some of your link URLs do not appear friendly to humans or search engines.", WHAT["friendly"], HOW["friendly"], [f"{u['url']}  ({', '.join(u['reasons'])})" for u in uf[:8]], priority=LOW, rec_title="Update Link URLs to be more readable"))
    else:
        c.append(Check("friendly", "Friendly Links", PASS, "Your link URLs appear friendly to humans and search engines.", WHAT["friendly"], HOW["friendly"]))
    return c


def rankings_checks(d: dict) -> list[Check]:
    ext = d["external"]
    rk = ext.get("rankings", {})
    c: list[Check] = []
    if not rk.get("available"):
        return [Check("rankings", "Top Organic Keyword Rankings", INFO, "", hide=True)]
    rows = rk.get("rows", [])
    depth = rk.get("depth", 20)
    buckets = {"Position 1": 0, "Position 2-3": 0, "Position 4-10": 0, "Position 11-20": 0}
    if depth > 20:
        buckets.update({"Position 21-30": 0, f"Position 31-{depth}": 0})
    buckets["Not in top " + str(depth)] = 0
    for r in rows:
        pos = r.get("position")
        if pos is None:
            buckets["Not in top " + str(rk.get("depth", 20))] += 1
        elif pos == 1:
            buckets["Position 1"] += 1
        elif pos <= 3:
            buckets["Position 2-3"] += 1
        elif pos <= 10:
            buckets["Position 4-10"] += 1
        elif pos <= 20:
            buckets["Position 11-20"] += 1
        elif pos <= 30 and "Position 21-30" in buckets:
            buckets["Position 21-30"] += 1
        elif f"Position 31-{depth}" in buckets:
            buckets[f"Position 31-{depth}"] += 1
        else:
            buckets["Not in top " + str(depth)] += 1
    page1 = buckets["Position 1"] + buckets["Position 2-3"] + buckets["Position 4-10"]
    c.append(Check("rankings", "Top Organic Keyword Rankings", PASS if page1 >= max(1, len(rows) // 3) else WARN,
                   f"Your site ranks on page one for {page1} of the {len(rows)} keywords checked in {rk.get('location')}.", WHAT["rankings"], HOW["rankings"],
                   priority=MED, weight=3, rec_title="Improve keyword rankings", kind="rankings", extra={"rows": rows, "location": rk.get("location")}))
    c.append(Check("positions", "Organic Keyword Positions", INFO, "This provides a summary of your Organic Keyword Ranking positions. The higher you rank, the more likely you are to capture traffic; research indicates up to 92% of clicks occur on the first page.", "", "", kind="positions", extra={"buckets": buckets}))
    aio_rows = [r for r in rows if r.get("ai_overview")]
    cited = [r for r in aio_rows if r.get("ai_overview_cited")]
    lp = [r for r in rows if r.get("local_pack_position")]
    if aio_rows:
        c.append(Check("aio", "Google AI Overview Visibility", PASS if cited else WARN,
                       f"Google shows an AI Overview for {len(aio_rows)} of the {len(rows)} keywords checked, and your site is cited in {len(cited)} of them.",
                       WHAT["aio"], HOW["aio"], [f"{r['keyword']}: {'cited' if r.get('ai_overview_cited') else 'not cited'}" for r in aio_rows], priority=MED, weight=2, rec_title="Get cited in Google AI Overviews"))
    else:
        c.append(Check("aio", "Google AI Overview Visibility", INFO, "Google did not show an AI Overview for the keywords checked.", WHAT["aio"], HOW["aio"]))
    if any(r.get("local_pack_names") for r in rows):
        c.append(Check("localpack", "Local Pack Visibility", PASS if lp else WARN, f"Your business appears in the Google local pack for {len(lp)} of the keywords that triggered one.", WHAT["gbp"], HOW["gbp_complete"],
                       [f"{r['keyword']}: {'#' + str(r['local_pack_position']) if r.get('local_pack_position') else 'not shown'} ({', '.join(n for n in r['local_pack_names'] if n)})" for r in rows if r.get("local_pack_names")], priority=MED, weight=2, rec_title="Improve local pack visibility"))
    return c


def usability_checks(d: dict) -> list[Check]:
    p, ext, br = d["page"], d["external"], d["browser"]
    c: list[Check] = []
    shots = br.get("screenshots", {})
    c.append(Check("devices", "Device Rendering", INFO, "This check visually demonstrates how your page renders on different devices. It is important that your page is optimised for mobile and tablet experiences as today the majority of web traffic comes from these sources.", WHAT["devices"], HOW["devices"], kind="devices", extra={"shots": shots}))
    psi = ext.get("pagespeed_mobile", {})
    if psi.get("available") and psi.get("has_field_data"):
        f = psi["field"]

        def cat(k):
            return (f.get(k) or {}).get("category", "N/A")

        lcp, inp, cls = cat("LARGEST_CONTENTFUL_PAINT_MS"), cat("INTERACTION_TO_NEXT_PAINT"), cat("CUMULATIVE_LAYOUT_SHIFT_SCORE")
        ok = psi.get("field_category") == "FAST"
        c.append(Check("cwv", "Google's Core Web Vitals", PASS if ok else (WARN if psi.get("field_category") == "AVERAGE" else FAIL),
                       "Google is reporting that your page passes the Core Web Vitals assessment." if ok else "Google is reporting that your page does not pass the Core Web Vitals assessment.",
                       WHAT["cwv"], HOW["cwv"], priority=MED, weight=3, rec_title="Improve Core Web Vitals", kind="cwv",
                       extra={"metrics": [{"label": "LCP", "value": (f.get("LARGEST_CONTENTFUL_PAINT_MS") or {}).get("percentile"), "unit": "ms", "cat": lcp},
                                          {"label": "INP", "value": (f.get("INTERACTION_TO_NEXT_PAINT") or {}).get("percentile"), "unit": "ms", "cat": inp},
                                          {"label": "CLS", "value": ((f.get("CUMULATIVE_LAYOUT_SHIFT_SCORE") or {}).get("percentile") or 0) / 100, "unit": "", "cat": cls}]}))
    elif psi.get("available"):
        c.append(Check("cwv", "Google's Core Web Vitals", INFO, "Google is indicating that they do not have 'sufficient real-world speed data for this page' in order to make a Core Web Vitals assessment. This can occur for smaller websites or those that are not crawlable by Google.", WHAT["cwv"], HOW["cwv"]))
    else:
        c.append(Check("cwv", "Google's Core Web Vitals", INFO, "", hide=True))
    vp = p["viewport"]
    c.append(Check("viewport", "Use of Mobile Viewports", PASS if vp and "width=device-width" in vp else FAIL,
                   "Your page specifies a Viewport matching the device's size, allowing it to render appropriately across devices." if vp and "width=device-width" in vp else "Your page does not specify a responsive Viewport.",
                   WHAT["viewport"], HOW["viewport"], priority=HIGH, weight=3, rec_title="Add a mobile Viewport tag"))
    c.append(Check("flash", "Flash Used?", FAIL if p["flash"] else PASS, "Flash content has been identified on your page." if p["flash"] else "No Flash content has been identified on your page.", WHAT["flash"], HOW["flash"], priority=HIGH, rec_title="Remove Flash content"))
    ifr = [i for i in p["iframes"] if i]
    c.append(Check("iframes", "iFrames Used?", WARN if ifr else PASS, "Your page appears to be using iFrames." if ifr else "Your page does not appear to be using iFrames.", WHAT["iframes"], HOW["iframes"], ifr[:5], priority=LOW, rec_title="Remove iFrames"))
    fav = d.get("favicon", {})
    c.append(Check("favicon", "Favicon", PASS if fav.get("present") else FAIL, "Your page has specified a Favicon." if fav.get("present") else "Your page has not specified a Favicon.", WHAT["favicon"], HOW["favicon"], priority=LOW, rec_title="Add a Favicon"))
    em = p["emails"]
    c.append(Check("email", "Email Privacy", WARN if em else PASS, "Email addresses have been found in plain text." if em else "No email addresses have been found in plain text.", WHAT["email"], HOW["email"], em[:5], priority=LOW, rec_title="Remove Clear Text Email Addresses"))
    return c


def performance_checks(d: dict) -> list[Check]:
    p, res, br, ext = d["page"], d["resources"], d["browser"], d["external"]
    c: list[Check] = []
    t = br.get("timing") or {}
    if t.get("load"):
        srv, dcl, load = (t.get("responseStart") or 0) / 1000, (t.get("domContentLoaded") or 0) / 1000, (t.get("load") or 0) / 1000
        st = PASS if load <= 4 else (WARN if load <= 7 else FAIL)
        c.append(Check("speed", "Website Load Speed", st, "Your page loads in a reasonable amount of time." if st == PASS else "Your page takes a long time to load.", WHAT["speed"], HOW["speed"], priority=MED, weight=3, rec_title="Improve page load speed", kind="timing",
                       extra={"metrics": [{"label": "Server Response", "value": f"{srv:.3f}s"}, {"label": "All Page Content Loaded", "value": f"{dcl:.1f}s"}, {"label": "All Page Scripts Complete", "value": f"{load:.1f}s"}]}))
    else:
        c.append(Check("speed", "Website Load Speed", INFO, "", hide=True))
    tw = res.get("total_wire") or 0
    if tw:
        st = PASS if tw <= 5_000_000 else (WARN if tw <= 8_000_000 else FAIL)
        c.append(Check("size", "Website Download Size", st, "Your page's file size is reasonably low which is good for Page Load Speed and user experience." if st == PASS else "Your page's file size is large, which will slow down loading, especially on mobile connections.",
                       WHAT["size"], HOW["size"], priority=MED, weight=2, rec_title="Reduce the page download size", kind="size",
                       extra={"total": fmt_mb(tw), "breakdown": [{"label": k.upper() if k != "images" else "Images", "value": fmt_mb(v)} for k, v in res["wire_bytes"].items()]}))
        comp = res.get("total_compression_pct", 0)
        text_comp = min(res["compression_pct"].get(k, 0) for k in ("html", "css", "js") if res["raw_bytes"].get(k)) if any(res["raw_bytes"].get(k) for k in ("html", "css", "js")) else 0
        st = PASS if text_comp >= 50 else (WARN if text_comp >= 20 else FAIL)
        c.append(Check("compression", "Compression Usage (Gzip, Deflate, Brotli)", st, "Your website appears to be using a reasonable level of compression." if st == PASS else "Your website does not appear to be compressing text files effectively.",
                       WHAT["compression"], HOW["compression"], priority=MED, weight=2, rec_title="Enable text compression", kind="compression",
                       extra={"total": comp, "rows": [{"label": k.upper() if k != "images" else "Images", "pct": res["compression_pct"][k], "raw": fmt_mb(res["raw_bytes"][k])} for k in ("html", "css", "js", "images", "other")] + [{"label": "Total", "pct": comp, "raw": fmt_mb(res["total_raw"])}]}))
        cnt = res["counts"]
        c.append(Check("resources", "Resources Breakdown", INFO, "This check displays the total number of files that need to be retrieved from web servers to load your page.", WHAT["resources"], HOW["resources"], kind="resources",
                       extra={"metrics": [{"label": "Total Objects", "value": res["total_objects"]}, {"label": "Number of HTML Pages", "value": cnt["html"]}, {"label": "Number of JS Resources", "value": cnt["js"]}, {"label": "Number of CSS Resources", "value": cnt["css"]}, {"label": "Number of Images", "value": cnt["images"]}, {"label": "Other Resources", "value": cnt["other"]}]}))
    psi = ext.get("pagespeed_mobile", {})
    if psi.get("available") and psi.get("scores"):
        sc = psi["scores"].get("performance")
        lab = psi.get("lab", {})
        c.append(Check("psi", "Google PageSpeed Insights (Mobile)", PASS if sc >= 90 else (WARN if sc >= 50 else FAIL), f"Your page scores {sc}/100 for mobile performance in Google's Lighthouse lab test.", WHAT["cwv"], HOW["cwv"],
                       [f"{k.replace('-', ' ').title()}: {v.get('display')}" for k, v in lab.items() if v.get("display")] + [f"Opportunity: {o['title']} ({o.get('savings') or ''})" for o in psi.get("opportunities", [])[:5]], priority=MED, weight=3, rec_title="Improve mobile PageSpeed score"))
    amp = p["amp"]
    c.append(Check("amp", "Google Accelerated Mobile Pages (AMP)", INFO, "This page does not appear to have AMP Enabled." if not any(amp.values()) else "This page appears to have AMP indicators.", WHAT["amp"], HOW["amp"],
                   [f"{'✓' if v else '✗'} {k.replace('_', ' ').title()}" for k, v in amp.items()]))
    je = br.get("js_errors") or []
    c.append(Check("jserrors", "JavaScript Errors", WARN if je else PASS, "Your page is reporting JavaScript errors." if je else "Your page is not reporting any JavaScript errors.", WHAT["jserrors"], HOW["jserrors"], je[:5], priority=LOW, rec_title="Fix JavaScript errors"))
    proto = (br.get("protocol") or "").lower()
    h2 = proto in ("h2", "h3") or bool(res.get("protocols", {}).get("h2")) or bool(res.get("protocols", {}).get("h3"))
    c.append(Check("http2", "HTTP2 Usage", PASS if h2 else FAIL, "Your website is using the recommended HTTP/2+ Protocol." if h2 else "Your website is not using the HTTP/2+ Protocol.", WHAT["http2"], HOW["http2"], [f"Detected: {proto or 'unknown'}"] if proto else [], priority=MED, weight=2, rec_title="Enable HTTP/2"))
    dep = p["deprecated_tags"]
    c.append(Check("deprecated", "Deprecated HTML", WARN if dep else PASS, "Deprecated HTML tags have been found within your page." if dep else "No deprecated HTML tags have been found within your page.", WHAT["deprecated"], HOW["deprecated"], [f"<{t}>" for t in dep], priority=LOW, rec_title="Remove deprecated HTML tags"))
    ins = p["inline_styles_count"]
    c.append(Check("inline", "Inline Styles", WARN if ins > 5 else PASS, "Your page appears to be using Inline Styles." if ins > 5 else "Your page does not appear to be using significant Inline Styles.", WHAT["inline"], HOW["inline"],
                   [f"{ins} elements with inline style attributes"] + p["inline_styles_sample"][:6] if ins > 5 else [], priority=LOW, rec_title="Remove Inline Styles"))
    return c


def social_checks(d: dict) -> list[Check]:
    p = d["page"]
    s = p["social"]
    c: list[Check] = []

    def linkcheck(cid, name, key, noun):
        if s.get(key):
            c.append(Check(cid, f"{name} Linked", PASS, f"Your page has a link to a {noun}.", WHAT["social_link"], HOW["social_link"], [s[key]]))
        else:
            c.append(Check(cid, f"{name} Linked", WARN, f"No associated {noun} was found linked from your page.", WHAT["social_link"], HOW["social_link"], priority=LOW, rec_title=f"Create and link a {noun}"))

    linkcheck("facebook", "Facebook Page", "facebook", "Facebook Page")
    og = p["og"]
    c.append(Check("og", "Facebook Open Graph Tags", PASS if og.get("og:title") else WARN, "Your page is using Facebook Open Graph Tags." if og.get("og:title") else "Your page is not using Facebook Open Graph Tags.", WHAT["og"], HOW["og"],
                   [f"{k}: {str(v)[:90]}" for k, v in list(og.items())[:6]] if og else [], priority=LOW, rec_title="Add Open Graph Tags"))
    px = p["facebook_pixel"]
    c.append(Check("pixel", "Facebook Pixel", PASS if px else INFO, "Your page has a Facebook Pixel installed." if px else "Your page does not appear to have a Facebook Pixel installed.", WHAT["pixel"], HOW["pixel"], [f"Pixel ID: {px}"] if px else []))
    linkcheck("x", "X (formerly Twitter) Account", "x", "X Profile")
    tw = p["twitter"]
    c.append(Check("xcards", "X Cards", PASS if tw.get("twitter:card") or tw.get("twitter:title") else WARN, "Your page is using X Cards." if tw else "Your page is not using X Cards.", WHAT["xcards"], HOW["xcards"], priority=LOW, rec_title="Add X Card tags"))
    linkcheck("instagram", "Instagram", "instagram", "Instagram Profile")
    linkcheck("linkedin", "LinkedIn Page", "linkedin", "LinkedIn Profile")
    linkcheck("youtube", "YouTube Channel", "youtube", "YouTube Channel")
    yt = p.get("youtube") or {}
    if yt.get("linked") and yt.get("subscribers") is not None:
        n = parse_count(yt["subscribers"])
        st = PASS if n >= 1000 else WARN
        c.append(Check("youtube_activity", "YouTube Channel Activity", st, "You have a healthy number of YouTube Channel subscribers." if st == PASS else "You have a low number of YouTube Channel subscribers.", WHAT["youtube_activity"], HOW["youtube_activity"], [f"Subscribers: {yt['subscribers']}"], priority=LOW, rec_title="Increase your YouTube Channel subscribers"))
    return c


def parse_count(s: str) -> float:
    s = str(s).replace(",", "").strip()
    mult = 1
    if s.endswith("K"):
        mult, s = 1000, s[:-1]
    elif s.endswith("M"):
        mult, s = 1_000_000, s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return 0


def local_checks(d: dict) -> list[Check]:
    p, ext = d["page"], d["external"]
    c: list[Check] = []
    blk = p.get("local_schema_block")
    if blk:
        rows = flatten_schema(blk)
        c.append(Check("local_schema", "Local Business Schema", PASS, "Local Business Schema identified on the page.", WHAT["local_schema"], HOW["local_schema"], kind="schema", extra={"types": p["local_schema"], "rows": rows[:40]}))
    else:
        c.append(Check("local_schema", "Local Business Schema", WARN, "No Local Business Schema was identified on the page.", WHAT["local_schema"], HOW["local_schema"], priority=MED, rec_title="Add Local Business Schema"))
    g = ext.get("gbp", {})
    if g.get("available") and g.get("found") and not g.get("unverified"):
        c.append(Check("gbp", "Google Business Profile Identified", PASS, "A Google Business Profile was identified that links to this website.", WHAT["gbp"], HOW["gbp"], [g.get("title")]))
        nap = [("Address", g.get("address")), ("Phone", g.get("phone")), ("Site", g.get("website")), ("Category", ", ".join(g["type"]) if isinstance(g.get("type"), list) else g.get("type"))]
        missing = [k for k, v in nap if not v]
        c.append(Check("gbp_complete", "Google Business Profile Completeness", PASS if not missing else WARN, "Important business details are present on the Google Business Profile." if not missing else f"Some business details are missing from the Google Business Profile ({', '.join(missing)}).", WHAT["gbp_complete"], HOW["gbp_complete"], [f"{k}: {v}" for k, v in nap if v], priority=MED, rec_title="Complete your Google Business Profile"))
        r, n = g.get("rating"), g.get("reviews")
        if r is not None:
            st = PASS if (r >= 4.3 and (n or 0) >= 10) else WARN
            c.append(Check("reviews", "Google Reviews", st, "The Google Business Profile has a good rating and review count." if st == PASS else "The Google Business Profile could use more, or better, reviews.", WHAT["reviews"], HOW["reviews"], kind="reviews", extra={"rating": r, "count": n}, priority=MED, rec_title="Grow your Google reviews"))
    elif g.get("available") and g.get("found"):
        c.append(Check("gbp", "Google Business Profile Identified", WARN, f"A nearby listing named '{g.get('title')}' was found, but its website does not match this domain.", WHAT["gbp"], HOW["gbp"], [f"Listing website: {g.get('website') or 'none'}"], priority=MED, rec_title="Link your Google Business Profile to this website"))
    elif g.get("available"):
        c.append(Check("gbp", "Google Business Profile Identified", WARN, "No Google Business Profile could be identified for this business.", WHAT["gbp"], HOW["gbp"], priority=MED, rec_title="Create or claim a Google Business Profile"))
    else:
        c.append(Check("gbp", "Google Business Profile Identified", INFO, "", hide=True))
    return c


def flatten_schema(o, prefix="") -> list[list[str]]:
    rows = []
    if isinstance(o, dict):
        for k, v in o.items():
            if k in ("@context", "review", "reviews"):
                continue
            if isinstance(v, (dict, list)):
                rows.append([prefix + k, ""])
                rows += flatten_schema(v, prefix + "  ")
            else:
                rows.append([prefix + k, str(v)[:110]])
    elif isinstance(o, list):
        for v in o:
            if isinstance(v, (dict, list)):
                rows += flatten_schema(v, prefix)
            else:
                rows.append([prefix, str(v)[:110]])
    return rows


def technology_checks(d: dict) -> list[Check]:
    p, dns = d["page"], d["dns"]
    c: list[Check] = []
    c.append(Check("tech", "Technology List", INFO, "These software or coding libraries have been identified on your page.", "", "", kind="techlist", extra={"tech": p["tech"]}))
    c.append(Check("ip", "Server IP Address", INFO, ", ".join(dns.get("a") or []) or "Unknown", "", ""))
    c.append(Check("ns", "DNS Servers", INFO, ", ".join(x.rstrip(".") for x in dns.get("ns") or []) or "Unknown", "", ""))
    c.append(Check("server", "Web Server", INFO, d.get("server") or "Unknown", "", ""))
    c.append(Check("charset", "Charset", INFO, d.get("charset") or "Unknown", "", ""))
    c.append(Check("dmarc", "DMARC Record", PASS if dns.get("dmarc") else WARN, "This site appears to have a valid DMARC record in place." if dns.get("dmarc") else "No DMARC record was found for this domain.", WHAT["dmarc"], HOW["dmarc"], [dns["dmarc"]] if dns.get("dmarc") else [], priority=LOW, rec_title="Add a DMARC record"))
    c.append(Check("spf", "SPF Record", PASS if dns.get("spf") else WARN, "This site appears to have an SPF record." if dns.get("spf") else "No SPF record was found for this domain.", WHAT["spf"], HOW["spf"], [dns["spf"]] if dns.get("spf") else [], priority=LOW, rec_title="Add an SPF record"))
    return c


def citation_checks(d: dict) -> list[Check]:
    ci = d["external"].get("citations", {})
    c: list[Check] = []
    w = ci.get("wikipedia", {})
    if w.get("available"):
        links = w.get("links_to_site") or []
        c.append(Check("wikipedia", "Wikipedia Citations", PASS if links else FAIL, "Wikipedia pages link to your website." if links else "We could not find any Wikipedia pages linking to your website.", WHAT["wikipedia"], HOW["wikipedia"], [l["title"] for l in links[:5]], priority=LOW, weight=1, rec_title="Earn Wikipedia Citations"))
    else:
        c.append(Check("wikipedia", "Wikipedia Citations", INFO, "", hide=True))
    for key, title, what, how, rec in (("reddit", "Reddit Citations", WHAT["reddit"], HOW["reddit"], "Earn Reddit Citations"), ("youtube", "YouTube Citations", WHAT["youtube_cite"], HOW["youtube_cite"], "Earn YouTube Citations")):
        r = ci.get(key, {})
        if r.get("available"):
            n = r.get("count", 0)
            c.append(Check(key, title, PASS if n else FAIL, f"Your website is referenced from {title.split()[0]}." if n else f"We could not find any {title.split()[0]} pages referencing your website.", what, how, [f"{x['title']}\n{x['snippet']}" for x in r.get("results", [])[:3]], priority=LOW, weight=1, rec_title=rec))
        else:
            c.append(Check(key, title, INFO, "", hide=True))
    return c


def prompt_checks(d: dict, ai: dict | None) -> list[Check]:
    gem = d["external"].get("gemini", {})
    engines: dict[str, list[dict]] = {}
    if gem.get("available") and gem.get("rows"):
        engines["Gemini"] = gem["rows"]
    for name in ("Claude", "ChatGPT", "Perplexity"):
        rows = ((ai or {}).get("prompt_results") or {}).get(name.lower())
        if rows:
            engines[name] = rows
    c: list[Check] = []
    if not engines:
        return [Check("prompts", "Platform Snapshot", INFO, "", hide=True)]
    total = sum(len(r) for r in engines.values())
    mentioned = sum(1 for r in engines.values() for x in r if x.get("mentioned"))
    per = {e: sum(1 for x in r if x.get("mentioned")) for e, r in engines.items()}
    brand = d["brand"]
    summary = f"{brand} mentioned in {mentioned} / {total} AI responses (" + " · ".join(f"{e}: {n}" for e, n in per.items()) + ")."
    rate = mentioned / total if total else 0
    st = PASS if rate >= 0.5 else (WARN if rate >= 0.2 else FAIL)
    c.append(Check("prompts", "Platform Snapshot", st, "Your business is cited across the LLMs." if st == PASS else ("Your business is only surfaced by LLMs for some discovery questions." if st == WARN else "Your business is rarely surfaced by LLMs for discovery questions."), WHAT["prompts"], HOW["prompts"], [summary], priority=MED, weight=3, rec_title="Improve AI prompt visibility", extra={"rate": rate}))
    # competitor table
    counts: dict[str, int] = {}
    positions: dict[str, list[int]] = {}
    for rows in engines.values():
        for x in rows:
            for i, b in enumerate(x.get("businesses") or []):
                counts[b] = counts.get(b, 0) + 1
                positions.setdefault(b, []).append(i + 1)
    key = "".join(ch for ch in brand.lower() if ch.isalnum())
    comp = sorted(counts.items(), key=lambda kv: -kv[1])[:15]
    comp_rows = [{"name": n + (" (You)" if key in "".join(ch for ch in n.lower() if ch.isalnum()) else ""), "rate": round(100 * cnt / total), "avg_pos": round(sum(positions[n]) / len(positions[n]), 1)} for n, cnt in comp]
    if comp_rows:
        c.append(Check("competitors", "Competitor Visibility", INFO, "How often each business is cited when LLMs answer questions about your space, and its average position when mentioned.", "", "", kind="competitors", extra={"rows": comp_rows}))
    # prompt by prompt
    prompts = list(dict.fromkeys(x["prompt"] for rows in engines.values() for x in rows))
    grid = []
    for pr in prompts:
        cells = {}
        for e, rows in engines.items():
            m = next((x for x in rows if x["prompt"] == pr), None)
            cells[e] = {"rank": m.get("rank") if m else None, "mentioned": bool(m and m.get("mentioned")), "businesses": (m.get("businesses") or [])[:5] if m else []}
        grid.append({"prompt": pr, "cells": cells})
    c.append(Check("promptgrid", "Prompt by Prompt Ranking", INFO, "Where your business ranks in each LLM's answer, prompt by prompt. LLM responses vary between runs, so treat these as a directional indicator.", "", "", kind="promptgrid", extra={"engines": list(engines), "rows": grid}))
    return c


# --------------------------------------------------------------------------- assembly


def score_section(checks: list[Check]) -> float | None:
    tot = sum(c.d["weight"] for c in checks if c.d["status"] in (PASS, FAIL, WARN))
    if not tot:
        return None
    got = sum(c.d["weight"] * (1 if c.d["status"] == PASS else 0.5 if c.d["status"] == WARN else 0) for c in checks if c.d["status"] in (PASS, FAIL, WARN))
    return round(100 * got / tot)


def section(sid, title, noun, checks, scored=True, weight=1, intro=None, score_override=None):
    checks = [c for c in checks if not c.d.get("hide")]
    sc = score_override if score_override is not None else (score_section(checks) if scored else None)
    v = verdict(sc, noun) if sc is not None else ("", "")
    return {"id": sid, "title": title, "score": sc, "weight": weight if scored else 0, "verdict": v[0], "verdict_short": v[1],
            "intro": intro, "checks": [c.d for c in checks]}


def build(run_dir: Path, rtype: str, action_plan: bool) -> dict:
    d = read_json(run_dir / "data.json")
    ai = read_json(run_dir / "ai.json", {})
    cfg = load_config()
    sections = []
    if rtype in ("seo", "crawl"):
        onp = onpage_checks(d)
        geo = geo_core_checks(d)
        sections = [
            section("onpage", "On-Page SEO Results", "On-Page SEO", onp, weight=30, intro="On-Page SEO is important to ensure Search Engines can understand your content appropriately and help it rank for relevant keywords."),
            section("geo", "Generative Engine Optimisation (GEO)", "Generative Engine Optimisation", geo, weight=15, intro="GEO is important to ensure LLMs and AI Search Engines can effectively crawl your content and understand the underlying entity structure. Visibility in LLMs is becoming a rapidly growing traffic source."),
            section("rankings", "Rankings", "Rankings", rankings_checks(d), scored=False),
            section("links", "Links", "Links", links_checks(d), weight=20, intro="Backlinks are one of the most important ranking factors. Links from authoritative, relevant websites improve the ranking ability of your site."),
            section("usability", "Usability", "usability", usability_checks(d), weight=15, intro="Usability is important to maximise your available audience and minimise user bounce rates, which can indirectly affect your search engine rankings."),
            section("performance", "Performance Results", "performance", performance_checks(d), weight=20, intro="Performance is important to ensure a good user experience and reduced bounce rates, which can also indirectly affect your search engine rankings."),
            section("social", "Social Results", "Social", social_checks(d), scored=False),
            section("local", "Local SEO", "Local SEO", local_checks(d), scored=False),
            section("technology", "Technology Results", "Technology", technology_checks(d), scored=False),
        ]
        dial_ids = ["onpage", "geo", "links", "usability", "performance"]
        title = f"SEO Audit for {d['domain']}" if rtype == "seo" else f"Crawl Report for {d['domain']}"
        intro = ("This report lists every page crawled on your website with the SEO issues found on each, grouped by issue type and priority, alongside the homepage audit scores. "
                 "Fixing high-priority issues first will have the largest effect on how well the site is crawled, indexed and ranked.") if rtype == "crawl" else ("This report grades your website based on the strength of various SEO factors such as On-Page Optimisation, Off-Page Links, Usability, Performance and more. "
                 "The overall grade is on an A+ to F scale, with most major, industry-leading websites in the A range. Improving your grade will generally make your website perform better for users and rank better in search engines. "
                 "There are recommendations for improving your website at the top of the report. Feel free to reach out to us if you'd like help improving your website's SEO!")
    elif rtype in ("local", "gbp"):
        import local_checks as lc
        g = d["external"].get("gbp", {})
        addr = ((g.get("details") or {}).get("address") or g.get("address") or "")
        who = d["brand"] + (f", {addr}" if addr else "")
        if rtype == "local":
            gbp_sec = lc.gbp_identified_checks(d)
            rev = lc.google_reviews_checks(d)
            sections = [
                section("gbp", "Google Business Profile", "Google Business Profile", gbp_sec, weight=25, intro="Your Google Business Profile is the listing customers see in Maps and local search. It needs to be identified, complete and consistent with your website."),
                section("reviews", "Google Reviews", "reviews", rev, weight=15, intro="Ratings and reviews drive both customer trust and local rankings."),
                section("listings", "Other Listings", "Other Listings", lc.yelp_checks(d), weight=10, intro="Listings on other platforms act as citations that confirm your business details to search engines and AI assistants."),
                section("onpage", "Website On-Page SEO Results", "On-Page SEO", onpage_checks(d, geo_variant=True) + [c for c in local_checks(d) if c.d["id"] == "local_schema"], weight=25, intro="On-Page SEO is important to ensure Search Engines can understand your content and connect it to your local business."),
                section("rankings", "Website Rankings", "Rankings", rankings_checks(d), scored=False),
                section("links", "Website Backlinks", "Links", links_checks(d), weight=25, intro="Backlinks from local and industry websites are a strong signal of authority for local rankings."),
            ]
            dial_ids = ["gbp", "reviews", "listings", "onpage", "links"]
            title = f"Local SEO Audit for {who}"
            intro = ("This report evaluates your business's local SEO presence by the strength of several important factors including the business's Google Business Profile, website on-page SEO, rankings, backlinks, "
                     "listings on external platforms and reviews across platforms. The overall assessment is graded on a scale from A+ to F. Improving your Local SEO is key to better visibility in local searches and subsequently more leads for your business.")
        else:
            sections = [
                section("complete", "Profile Completeness", "profile completeness", lc.gbp_completeness_checks(d), weight=35, intro="A complete profile gives Google every signal it needs to show your business, and gives customers every reason to choose it."),
                section("keyword", "Keyword", "keyword usage", lc.gbp_keyword_checks(d), weight=15, intro="Relevance for your core keyword comes from the name, categories, description, reviews and posts."),
                section("reviews", "Reviews", "review profile", lc.gbp_review_checks(d), weight=35, intro="Review score, volume, recency and owner responses are all local ranking and conversion factors."),
                section("posts", "Posts", "posting activity", lc.gbp_post_checks(d), weight=15, intro="Regular posts keep the profile fresh and give customers reasons to act."),
            ]
            dial_ids = ["complete", "keyword", "reviews", "posts"]
            title = f"Google Business Profile Audit for {who}"
            intro = ("This report evaluates your Google Business Profile by the strength of several important factors including completed profile information, reviews volume, strength and responsiveness, keyword and post usage and more. "
                     "The overall assessment is graded on a scale from A+ to F. Improving your Google Business Profile is key to better visibility in local searches and subsequently more leads for your business.")
        label = "Local SEO" if rtype == "local" else "GBP"
    else:  # geo / aeo
        access = geo_core_checks(d)
        rb = d["robots"]
        access.insert(2, Check("robots", "Robots.txt", PASS if rb["present"] else FAIL, "Your website appears to have a robots.txt file." if rb["present"] else "Your website does not appear to have a robots.txt file.", WHAT["robots"], HOW["robots"], [rb["url"]] if rb["present"] else [], priority=LOW, rec_title="Add a robots.txt file"))
        sm = d["sitemap"]
        access.append(Check("sitemap", "XML Sitemaps", PASS if sm["present"] else FAIL, "Your website appears to have an XML Sitemap." if sm["present"] else "Your website does not appear to have an XML Sitemap.", WHAT["sitemap"], HOW["sitemap"], [sm["url"]] if sm["present"] else [], priority=MED, weight=2, rec_title="Add an XML Sitemap"))
        p = d["page"]
        access.append(Check("noindex", "Noindex Tag Test", FAIL if p["noindex_tag"] else PASS, "Your page is using the Noindex Tag which prevents indexing." if p["noindex_tag"] else "Your page is not using the Noindex Tag which prevents indexing.", WHAT["noindex"], HOW["noindex"], priority=HIGH, weight=3, rec_title="Remove the Noindex Tag"))
        access.append(Check("noindex_h", "Noindex Header Test", FAIL if d["noindex_header"] else PASS, "Your page is using the Noindex Header which prevents indexing." if d["noindex_header"] else "Your page is not using the Noindex Header which prevents indexing.", WHAT["noindex"], HOW["noindex"], priority=HIGH, weight=3, rec_title="Remove the Noindex Header"))
        identity = [c for c in access if c.d["id"] == "identity"]
        access = [c for c in access if c.d["id"] != "identity"]
        content = identity + ai_assessed_checks(ai)
        if rtype == "aeo":
            qh = p["question_headings"]
            content.append(Check("qheads", "Question Headings", PASS if len(qh) >= 3 else (WARN if qh else FAIL), f"Your page has {len(qh)} question-style headings that map to how people ask AI assistants." if qh else "Your page has no question-style headings.", WHAT["answers"], HOW["answers"], qh[:8], priority=MED, weight=2, rec_title="Add question-based headings"))
            content.append(Check("faqschema", "FAQ / Q&A Schema", PASS if p["faq_schema"] else INFO, "Your page includes FAQPage or QAPage structured data." if p["faq_schema"] else "Your page does not include FAQPage or QAPage structured data. Google no longer shows FAQ rich results, but Q&A markup can still help AI systems parse question-answer pairs.", WHAT["answers"], HOW["answers"]))
        pv = prompt_checks(d, ai)
        pv_score = None
        snap = next((c for c in pv if c.d["id"] == "prompts" and c.d["status"] != INFO), None)
        if snap:
            pv_score = round(100 * snap.d["extra"]["rate"])
        cit = citation_checks(d)
        cit_score = None
        measured = [c for c in cit if c.d["status"] in (PASS, FAIL)]
        if measured:
            cit_score = round(100 * sum(1 for c in measured if c.d["status"] == PASS) / len(measured))
        rk = rankings_checks(d)
        sections = [
            section("access", "LLM Accessibility", "Generative Engine Optimisation", access, weight=25, intro="LLM accessibility is important to ensure AI crawlers can reach and read your content and understand the underlying entity structure."),
            section("content", "LLM Content Analysis", "GEO content", content, weight=25, intro="Well-structured content that clearly expresses the entity, its offering and supporting detail is far easier for LLMs to parse, attribute and cite."),
            section("airank", "AI Search Rankings", "AI Search visibility", rk, scored=False),
            section("prompts", "Prompt Visibility", "AI prompt visibility", pv, weight=20, score_override=pv_score if pv_score is not None else None, scored=pv_score is not None,
                    intro="Prompt visibility measures how often, and how prominently, LLMs cite your business when answering real discovery questions."),
            section("citations", "Important Citations", "citations", cit, weight=10, score_override=cit_score, scored=cit_score is not None,
                    intro="High-authority sources that AI search engines cite most, such as Wikipedia, Reddit and YouTube, help establish your business as a recognised entity."),
            section("onpage", "Website On-Page SEO Results", "On-Page SEO", onpage_checks(d, geo_variant=True), weight=20, intro="On-Page SEO is important to ensure Search Engines and LLMs can understand your content appropriately."),
        ]
        dial_ids = ["access", "content", "prompts", "citations", "onpage"]
        label = "AEO" if rtype == "aeo" else "GEO"
        title = f"{label} Audit for {d['domain']}"
        intro = ("This report evaluates how well your website is positioned for " + ("Answer Engine Optimisation (AEO)" if rtype == "aeo" else "Generative Engine Optimisation (GEO)") +
                 " - how effectively AI Search Engines and Large Language Models (LLMs) can find, understand, trust and recommend your content. It reviews your identity and structured data, how readable your content is to AI crawlers, "
                 "and how your brand appears when people ask AI assistants about your products or services. As AI-driven search grows rapidly as a source of traffic and referrals, strengthening your " + label +
                 " helps ensure your business is surfaced and cited by these tools. You'll find recommendations for improvement throughout the report. Feel free to reach out if you'd like help improving your website's visibility in AI search!")

    sections = [s for s in sections if s["checks"]]
    scored = [s for s in sections if s["score"] is not None and s["weight"]]
    overall = round(sum(s["score"] * s["weight"] for s in scored) / sum(s["weight"] for s in scored)) if scored else 0
    dials = []
    for sid in dial_ids:
        s = next((x for x in sections if x["id"] == sid), None)
        if s is None or s["score"] is None:
            continue
        dials.append({"id": sid, "label": dial_label(sid, s["title"]), "score": s["score"]})
    recs = []
    for s in sections:
        for c in s["checks"]:
            if c["status"] in (FAIL, WARN) and c.get("rec_title"):
                recs.append({"title": c["rec_title"], "category": dial_label(s["id"], s["title"]), "priority": c["priority"], "check_id": c["id"], "section_id": s["id"]})
    order = {HIGH: 0, MED: 1, LOW: 2}
    recs.sort(key=lambda r: order[r["priority"]])
    v = verdict(overall, "page" if rtype in ("seo", "crawl") else label)
    if rtype in ("local", "gbp"):
        v = verdict(overall, label)
    report = {
        "type": rtype, "title": title, "intro": intro, "domain": d["domain"], "url": d["url"], "brand": d["brand"],
        "generated": d["collected_at"], "agency": cfg.get("agency", {}), "overall": overall, "grade": grade(overall),
        "verdict": v[0].replace("Your page is", "Your page is").replace("very good!", "very good") if rtype in ("seo", "crawl") else v[0],
        "dials": dials, "sections": sections, "recommendations": recs, "screenshots": d["browser"].get("screenshots", {}),
        "action_plan": (ai.get("action_plan") if action_plan else None), "executive_summary": ai.get("executive_summary"),
        "crawl": d.get("crawl"), "location": d.get("location"),
    }
    if rtype == "crawl" and d.get("crawl"):
        report["crawl_issues"] = crawl_issues(d["crawl"])
    return report


def dial_label(sid: str, title: str) -> str:
    return {"onpage": "On-Page SEO", "geo": "GEO", "links": "Links", "usability": "Usability", "performance": "Performance", "social": "Social", "local": "Local SEO", "technology": "Technology",
            "access": "Accessibility", "content": "Content", "prompts": "Prompt Visibility", "citations": "Citations", "rankings": "Rankings", "airank": "AI Search",
            "gbp": "GBP", "reviews": "Reviews", "listings": "Other Listings", "complete": "Completeness", "keyword": "Keyword", "posts": "Posts"}.get(sid, title)


def crawl_issues(crawl: dict) -> dict:
    issues: dict[str, dict] = {}

    def add(name, prio, url):
        issues.setdefault(name, {"issue": name, "priority": prio, "pages": []})["pages"].append(url)

    for pg in crawl.get("pages", []):
        u = pg["url"]
        path = u.split("//", 1)[-1].split("/", 1)[-1]
        path = "/" + path if not path.startswith("/") else path
        if pg.get("status") and pg["status"] >= 400:
            add("Page Returns Error Status", "High", path)
            continue
        if pg.get("error"):
            add("Page Could Not Be Fetched", "High", path)
            continue
        if not pg.get("title"):
            add("Missing Title Tag", "High", path)
        elif pg["title_length"] > 60:
            add("Title Tag Too Long", "Low", path)
        elif pg["title_length"] < 30:
            add("Title Tag Too Short", "Low", path)
        if not pg.get("meta_description_length"):
            add("Missing Meta Description", "Medium", path)
        elif pg["meta_description_length"] > 160:
            add("Meta Description Too Long", "Low", path)
        if pg.get("h1_count", 0) == 0:
            add("Missing H1 Tag", "Medium", path)
        elif pg["h1_count"] > 1:
            add("Multiple H1 Tags", "Low", path)
        if pg.get("word_count", 0) < 300:
            add("Page Text Content Too Short", "Low", path)
        if pg.get("images_missing_alt"):
            add("Images Missing Alt Attributes", "Low", path)
        if pg.get("noindex"):
            add("Page Set to Noindex", "High", path)
        if not pg.get("canonical"):
            add("Missing Canonical Tag", "Low", path)
    per_page = []
    for pg in crawl.get("pages", []):
        path = "/" + pg["url"].split("//", 1)[-1].split("/", 1)[-1] if "/" in pg["url"].split("//", 1)[-1] else "/"
        items = [f"{i['issue']} ({i['priority']})" for i in issues.values() if path in i["pages"]]
        per_page.append({"page": path, "count": len(items), "issues": items})
    order = {"High": 0, "Medium": 1, "Low": 2}
    return {"issues": sorted(issues.values(), key=lambda i: (order[i["priority"]], -len(i["pages"]))), "pages": per_page, "count": crawl.get("count"), "truncated": crawl.get("truncated")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--type", default="seo", choices=["seo", "geo", "aeo", "crawl", "local", "gbp"])
    ap.add_argument("--no-action-plan", action="store_true")
    a = ap.parse_args()
    run = Path(a.run_dir).expanduser()
    rep = build(run, a.type, not a.no_action_plan)
    write_json(run / "report.json", rep)
    print(f"[build] {rep['title']}: overall {rep['overall']} ({rep['grade']}), {len(rep['recommendations'])} recommendations -> {run / 'report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
