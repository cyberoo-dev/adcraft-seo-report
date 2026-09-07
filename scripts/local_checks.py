"""Local SEO and Google Business Profile checks (SEOptimer 'Local SEO Audit' and 'GBP Audit' equivalents).

Data comes from collect.py --local (SerpApi google_maps + google_maps_reviews + yelp). Every check that lacks
data is created with hide=True so the report simply omits it.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from build_report import Check, PASS, FAIL, WARN, INFO, HIGH, MED, LOW, WHAT, HOW

WHAT_L = {
    "yelp": "Yelp is one of the most influential business review platforms. A Yelp listing is a valuable local citation: it builds visibility and trust, feeds business data to other platforms including Apple Maps and Bing, and helps search engines verify your name, address and phone number.",
    "listing_complete": "It is important your listing details are complete and correct, in particular the Name, Address and Phone (NAP). This helps customers find you and helps search engines match citations of your business across the web.",
    "listing_reviews": "Reviews and ratings on your listing build customer trust and reputation, and feed into the local search ecosystem that determines how prominently your business is shown.",
    "category": "The primary category is the strongest signal Google uses to decide which local searches your business should appear for. Additional categories broaden that coverage.",
    "hours": "Opening hours let Google show 'Open now' results and stop customers arriving when you are closed. Profiles without hours lose visibility for time-sensitive searches.",
    "photos": "Profiles with plenty of recent photos receive more clicks, direction requests and website visits. Google also uses photo activity as an engagement signal.",
    "description": "The business description is your chance to explain what you do, where you serve and why customers choose you. Google reads it for relevance.",
    "utm": "Adding UTM tags to the website link in your profile lets analytics attribute visits and conversions to Google Business Profile rather than lumping them into organic traffic.",
    "kw_name": "Keywords in the business name are a strong local ranking signal, although Google's guidelines only allow the real-world business name.",
    "kw_reviews": "When customers naturally mention your services and location in reviews, Google gains relevance signals for those terms.",
    "kw_desc": "Mentioning your core service and service area in the description and categories reinforces relevance for local searches.",
    "kw_posts": "Posts that mention your core services and locations add fresh relevance signals to the profile.",
    "score": "Your average star rating is one of the first things customers see and is a confirmed local ranking factor.",
    "count": "Review volume signals popularity and trust. Competitors with more reviews will often outrank a business with a higher rating but fewer reviews.",
    "frequency": "A steady flow of new reviews matters more than a large but stale total. Google favours businesses that are being reviewed now.",
    "response": "Responding to reviews shows customers and Google that the business is active and engaged, and can lift conversion from the profile.",
    "negative": "Unanswered negative reviews damage trust more than the review itself. A calm, prompt reply reassures future customers.",
    "posts": "Google Posts appear directly on your profile and in Maps. Regular posts keep the profile fresh and give customers reasons to act.",
    "qa": "The Questions and Answers section is public and often pre-filled by customers. Seeding it with common questions and answers prevents wrong answers from strangers.",
}
HOW_L = {
    "yelp": "Create or claim your Yelp listing, keep the details accurate and encourage genuine reviews.",
    "listing_complete": "Review the listing and update every field: name, address, phone, website, hours, categories and description.",
    "listing_reviews": "Be proactive in asking for reviews and respond to every negative review.",
    "category": "Choose the most specific primary category that matches your core service, then add every relevant secondary category.",
    "hours": "Add regular hours and keep holiday hours updated in the Google Business Profile dashboard.",
    "photos": "Upload real photos of the team, premises, work and products, and add new ones every month.",
    "description": "Write a 500 to 750 character description covering services, service area and differentiators, with your main keyword in the first sentence.",
    "utm": "Change the profile's website link to include utm_source=google&utm_medium=organic&utm_campaign=gbp.",
    "kw_name": "Do not stuff keywords into the name. If the registered trading name genuinely includes the service, use it consistently everywhere.",
    "kw_reviews": "When asking for reviews, prompt customers to mention the service they used and the suburb, without scripting the review.",
    "kw_desc": "Edit the description and categories to include your core service and the areas you serve.",
    "kw_posts": "Reference your services and locations naturally in each post.",
    "score": "Address the causes of low ratings, ask happy customers for reviews, and reply to every review.",
    "count": "Build a review-request habit: ask at the moment of delivery, use a short link or QR code, and follow up by SMS or email.",
    "frequency": "Aim for at least a few new reviews every month by making the request part of your delivery process.",
    "response": "Reply to every review within a few days, thanking the reviewer and referencing the service provided.",
    "negative": "Reply to each negative review promptly, acknowledge the issue and offer to resolve it offline.",
    "posts": "Publish a post at least every two weeks: offers, project highlights, news or tips, each with an image and a call to action.",
    "qa": "Add the five most common customer questions with clear answers from the business account.",
}


def _stars(n: float | None) -> str:
    n = int(round(n or 0))
    return "★" * n + "☆" * (5 - n)


def _months_between(iso_a: str | None, iso_b: str | None) -> float | None:
    try:
        a = datetime.fromisoformat(iso_a.replace("Z", "+00:00"))
        b = datetime.fromisoformat(iso_b.replace("Z", "+00:00"))
        return abs((a - b).days) / 30.4
    except Exception:  # noqa: BLE001
        return None


def _hours_rows(hours) -> list[list[str]]:
    rows = []
    days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    if isinstance(hours, list):
        m = {}
        for h in hours:
            if isinstance(h, dict):
                for k, v in h.items():
                    m[k.lower()] = v
        for d in days:
            v = m.get(d.lower())
            rows.append([d, v or "–"])
    elif isinstance(hours, dict):
        for d in days:
            rows.append([d, hours.get(d.lower()) or hours.get(d) or "–"])
    return rows


def gbp_identified_checks(d: dict) -> list[Check]:
    g = d["external"].get("gbp", {})
    c: list[Check] = []
    if not g.get("available"):
        return [Check("gbp", "Google Business Profile Identified", INFO, "", hide=True)]
    if not g.get("found"):
        return [Check("gbp", "Google Business Profile Identified", FAIL, "No Google Business Profile could be identified for this business.", WHAT["gbp"], HOW["gbp"], priority=HIGH, weight=3, rec_title="Create or claim a Google Business Profile")]
    if g.get("unverified"):
        return [Check("gbp", "Google Business Profile Identified", WARN, f"A nearby listing named '{g.get('title')}' was found, but its website does not match this domain.", WHAT["gbp"], HOW["gbp"], [f"Listing website: {g.get('website') or 'none'}"], priority=MED, weight=3, rec_title="Link your Google Business Profile to this website")]
    det = g.get("details") or {}
    c.append(Check("gbp", "Google Business Profile Identified", PASS, "A Google Business Profile was identified that links to this website.", WHAT["gbp"], HOW["gbp"], [g.get("title")], weight=3))
    cat = det.get("type") or g.get("type")
    nap = [("Address", det.get("address") or g.get("address")), ("Phone", det.get("phone") or g.get("phone")), ("Site", det.get("website") or g.get("website")), ("Category", ", ".join(cat) if isinstance(cat, list) else cat)]
    missing = [k for k, v in nap if not v]
    c.append(Check("gbp_complete", "Google Business Profile Completeness", PASS if not missing else WARN, "Important business details are present on the Google Business Profile." if not missing else f"Some business details are missing from the Google Business Profile ({', '.join(missing)}).", WHAT["gbp_complete"], HOW["gbp_complete"], [f"{k}: {v}" for k, v in nap if v], priority=MED, weight=2, rec_title="Complete your Google Business Profile"))
    return c


def google_reviews_checks(d: dict, for_local: bool = True) -> list[Check]:
    g = d["external"].get("gbp", {})
    if not (g.get("available") and g.get("found") and not g.get("unverified")):
        return [Check("reviews", "Google Reviews", INFO, "", hide=True)]
    r, n = g.get("rating"), g.get("reviews")
    recent = g.get("recent_reviews") or []
    dist = {k: 0 for k in (5, 4, 3, 2, 1)}
    for rv in recent:
        try:
            dist[int(round(float(rv.get("rating") or 0)))] += 1
        except Exception:  # noqa: BLE001
            pass
    c: list[Check] = []
    if r is None:
        return [Check("reviews", "Google Reviews", INFO, "", hide=True)]
    st = PASS if (r >= 4.3 and (n or 0) >= 10) else WARN
    c.append(Check("reviews", "Google Reviews", st, "The Google Business Profile has a good rating and review count." if st == PASS else "The Google Business Profile could use more, or better, reviews.", WHAT["reviews"], HOW["reviews"], kind="ratingdist", extra={"rating": r, "count": n, "dist": dist, "sample": len(recent)}, priority=MED, weight=3, rec_title="Encourage more GBP Reviews"))
    good = [rv for rv in recent if (rv.get("rating") or 0) >= 4 and rv.get("snippet")][:3]
    if good:
        c.append(Check("recent_reviews", "Recent Positive GBP Reviews", INFO, "", kind="reviewcards", extra={"reviews": [{"stars": _stars(rv["rating"]), "date": rv.get("date"), "text": rv["snippet"][:260]} for rv in good]}))
    return c


def yelp_checks(d: dict) -> list[Check]:
    y = d["external"].get("yelp", {})
    if not y.get("available"):
        return [Check("yelp", "Yelp Listing Identified", INFO, "", hide=True)]
    if not y.get("found"):
        return [Check("yelp", "Yelp Listing Identified", WARN, "No Yelp listing could be identified for this business.", WHAT_L["yelp"], HOW_L["yelp"], priority=LOW, weight=2, rec_title="Create a Yelp listing")]
    c = [Check("yelp", "Yelp Listing Identified", PASS, "A Yelp listing was identified for this business.", WHAT_L["yelp"], HOW_L["yelp"], [y.get("title")], weight=2)]
    fields = [("Phone", y.get("phone")), ("Categories", ", ".join(y.get("categories") or [])), ("Area", ", ".join(y.get("neighborhoods") or []) if isinstance(y.get("neighborhoods"), list) else y.get("neighborhoods")), ("Listing", y.get("link"))]
    missing = [k for k, v in fields[:2] if not v]
    c.append(Check("yelp_complete", "Yelp Listing Completeness", PASS if not missing else WARN, "Important business details are present on the Yelp listing." if not missing else f"Some details are missing from the Yelp listing ({', '.join(missing)}).", WHAT_L["listing_complete"], HOW_L["listing_complete"], [f"{k}: {v}" for k, v in fields if v], priority=LOW, weight=1, rec_title="Complete your Yelp listing"))
    if y.get("reviews"):
        c.append(Check("yelp_reviews", "Yelp Reviews", PASS if (y.get("rating") or 0) >= 4 else WARN, f"The Yelp listing has {y.get('reviews')} reviews with a {y.get('rating')} rating.", WHAT_L["listing_reviews"], HOW_L["listing_reviews"], priority=LOW, weight=1, rec_title="Encourage Yelp reviews"))
    else:
        c.append(Check("yelp_reviews", "Yelp Reviews", WARN, "There is no review information available for this Yelp listing.", WHAT_L["listing_reviews"], HOW_L["listing_reviews"], priority=LOW, weight=1, rec_title="Encourage Yelp reviews"))
    return c


# ----------------------------------------------------------------------------- GBP audit


def gbp_completeness_checks(d: dict) -> list[Check]:
    g = d["external"].get("gbp", {})
    if not (g.get("available") and g.get("found") and not g.get("unverified")):
        return [Check("gbp_missing", "Google Business Profile", FAIL, "No Google Business Profile linked to this website could be identified, so the profile could not be audited.", WHAT["gbp"], HOW["gbp"], priority=HIGH, weight=3, rec_title="Create or claim a Google Business Profile")]
    det = g.get("details") or {}
    c: list[Check] = []
    raw_type = det.get("type") or g.get("type")
    all_types = list(raw_type) if isinstance(raw_type, list) else ([raw_type] if raw_type else [])
    all_types += [t for t in (det.get("types") or g.get("types") or []) if t not in all_types]
    ptype = all_types[0] if all_types else None
    c.append(Check("category", "Primary Category", PASS if ptype else FAIL, "Your business has a Primary Category assigned." if ptype else "Your business has no Primary Category assigned.", WHAT_L["category"], HOW_L["category"], [ptype] if ptype else [], priority=HIGH, weight=3, rec_title="Set a Primary Category"))
    extra = all_types[1:]
    c.append(Check("categories", "Additional Categories", PASS if extra else WARN, "Your business has Additional Categories assigned." if extra else "Your business has no Additional Categories assigned.", WHAT_L["category"], HOW_L["category"], extra[:8], priority=LOW, weight=1, rec_title="Add Additional Categories"))
    addr = det.get("address") or g.get("address")
    c.append(Check("address", "Address", PASS if addr else FAIL, "Your business has a full address provided." if addr else "Your business has no address provided.", WHAT["gbp_complete"], HOW["gbp_complete"], [addr] if addr else [], priority=HIGH, weight=2, rec_title="Add your business address"))
    site = det.get("website") or g.get("website")
    c.append(Check("website", "Website", PASS if site else FAIL, "Your business has a Website URL provided." if site else "Your business has no Website URL provided.", WHAT["gbp_complete"], HOW["gbp_complete"], [site] if site else [], priority=HIGH, weight=2, rec_title="Add your website to the profile"))
    phone = det.get("phone") or g.get("phone")
    c.append(Check("phone", "Phone Number", PASS if phone else FAIL, "Your business has a Phone Number provided." if phone else "Your business has no Phone Number provided.", WHAT["gbp_complete"], HOW["gbp_complete"], [phone] if phone else [], priority=HIGH, weight=2, rec_title="Add a phone number"))
    hours = det.get("hours") or g.get("hours")
    rows = _hours_rows(hours) if not isinstance(hours, str) else []
    c.append(Check("hours", "Work Hours", PASS if hours else WARN, "Your business has Opening Hours provided." if hours else "Your business has no Opening Hours provided.", WHAT_L["hours"], HOW_L["hours"], [hours] if isinstance(hours, str) else [], priority=MED, weight=2, rec_title="Add opening hours", kind="hours" if rows else "row", extra={"rows": rows}))
    photos = det.get("images_count")
    if photos is not None:
        c.append(Check("photos", "Photos", PASS if photos >= 10 else (WARN if photos else FAIL), "Your business has photos provided." if photos >= 10 else ("Your business has only a few photos." if photos else "Your business has no photos."), WHAT_L["photos"], HOW_L["photos"], [str(photos)], priority=MED, weight=2, rec_title="Add more photos to your profile"))
    desc = det.get("description") or g.get("description")
    c.append(Check("description", "Business Description", PASS if desc and len(desc) > 100 else (WARN if desc else FAIL), "Your business has a description provided." if desc and len(desc) > 100 else ("Your business description is very short." if desc else "Your business has no description."), WHAT_L["description"], HOW_L["description"], [desc[:300]] if desc else [], priority=MED, weight=2, rec_title="Write a full business description"))
    if site:
        utm = "utm_" in site
        c.append(Check("utm", "UTM Tags in URL", PASS if utm else WARN, "Your Website Link includes UTM Tags for tracking." if utm else "Your Website Link does not include UTM Tags for tracking.", WHAT_L["utm"], HOW_L["utm"], priority=LOW, weight=1, rec_title="Use UTM tags in your Website Link"))
    qa = det.get("questions_and_answers")
    if qa is not None:
        c.append(Check("qa", "Questions & Answers", PASS if qa else WARN, f"Your profile has {qa} questions answered." if qa else "Your profile has no Questions & Answers.", WHAT_L["qa"], HOW_L["qa"], priority=LOW, weight=1, rec_title="Seed the Questions & Answers section"))
    return c


def gbp_keyword_checks(d: dict) -> list[Check]:
    g = d["external"].get("gbp", {})
    kw = (d.get("local_keyword") or (d.get("keywords_requested") or [""])[0] or "").strip()
    if not (g.get("available") and g.get("found") and not g.get("unverified")) or not kw:
        return [Check("kw_none", "Keyword", INFO, "", hide=True)]
    det = g.get("details") or {}
    kl = kw.lower()
    words = [w for w in re.findall(r"[a-z]+", kl) if len(w) > 2]

    def has(text: str | None) -> bool:
        t = (text or "").lower()
        return bool(t) and (kl in t or all(w in t for w in words))

    c: list[Check] = []
    c.append(Check("kw_name", "Keyword in Business Name", PASS if has(g.get("title")) else INFO, f'Your keyword "{kw}" was found in the Business Name.' if has(g.get("title")) else f'Your keyword "{kw}" was not found in the Business Name.', WHAT_L["kw_name"], HOW_L["kw_name"], weight=1))
    rt = det.get("type") or g.get("type") or ""
    cats = " ".join((rt if isinstance(rt, list) else [rt]) + (det.get("types") or []))
    c.append(Check("kw_cat", "Keyword in Categories", PASS if has(cats) else WARN, "Your keyword matches your profile categories." if has(cats) else "Your keyword was not found in your profile categories.", WHAT_L["kw_desc"], HOW_L["category"], priority=MED, weight=2, rec_title="Align categories with your keyword"))
    c.append(Check("kw_desc", "Keyword in Description", PASS if has(det.get("description")) else WARN, "Your keyword was found in the business description." if has(det.get("description")) else "Your keyword was not found in the business description.", WHAT_L["kw_desc"], HOW_L["kw_desc"], priority=LOW, weight=1, rec_title="Use your keyword in the description"))
    recent = g.get("recent_reviews") or []
    hits = [rv for rv in recent if has(rv.get("snippet"))]
    c.append(Check("kw_reviews", "Keyword in Reviews", PASS if hits else WARN, f"Your keyword was found in {len(hits)} of {len(recent)} recent reviews." if hits else "Your keyword was not found in recent review content.", WHAT_L["kw_reviews"], HOW_L["kw_reviews"], priority=LOW, weight=1, rec_title="Encourage use of keyword in reviews"))
    posts = det.get("posts") or []
    if posts:
        ph = [p for p in posts if has(p.get("text"))]
        c.append(Check("kw_posts", "Keyword in Posts", PASS if ph else WARN, "Your keyword was found in recent posts." if ph else "Your keyword was not found in recent posts.", WHAT_L["kw_posts"], HOW_L["kw_posts"], priority=LOW, weight=1, rec_title="Use keyword in GBP Posts"))
    return c


def gbp_review_checks(d: dict) -> list[Check]:
    g = d["external"].get("gbp", {})
    if not (g.get("available") and g.get("found") and not g.get("unverified")):
        return [Check("rv_none", "Reviews", INFO, "", hide=True)]
    r, n = g.get("rating"), g.get("reviews") or 0
    recent = g.get("recent_reviews") or []
    c: list[Check] = []
    if r is not None:
        st = PASS if r >= 4.5 else (WARN if r >= 4.0 else FAIL)
        c.append(Check("score", "Review Score", st, "Your business has an excellent review score." if st == PASS else ("Your business has a good review score." if st == WARN else "Your business has a low review score."), WHAT_L["score"], HOW_L["score"], [f"{r} {_stars(r)}"], priority=HIGH, weight=3, rec_title="Improve your review score"))
    st = PASS if n >= 100 else (WARN if n >= 20 else FAIL)
    c.append(Check("count", "Number of Reviews", st, "Your GBP has a strong number of reviews." if st == PASS else ("Your GBP has a moderate number of reviews." if st == WARN else "Your GBP has a low number of reviews."), WHAT_L["count"], HOW_L["count"], [str(n)], priority=MED if st == WARN else LOW, weight=2, rec_title="Encourage more GBP Reviews"))
    if len(recent) >= 2:
        span = _months_between(recent[0].get("iso_date"), recent[-1].get("iso_date"))
        per_month = round(len(recent) / span, 1) if span and span > 0 else None
        if per_month is not None:
            st = PASS if per_month >= 3 else (WARN if per_month >= 1 else FAIL)
            c.append(Check("frequency", "Review Frequency", st, "Customers are reviewing your business frequently." if st == PASS else ("Customers are reviewing your business at a moderate rate." if st == WARN else "The frequency with which customers review your business is low."), WHAT_L["frequency"], HOW_L["frequency"], [f"About {per_month} new reviews per month (last {len(recent)} reviews)"], priority=MED, weight=2, rec_title="Encourage more frequent GBP Reviews"))
        responded = [rv for rv in recent if rv.get("response")]
        share = len(responded) / len(recent)
        st = PASS if share >= 0.7 else (WARN if share >= 0.3 else FAIL)
        c.append(Check("response", "Owner Review Response Frequency", st, "You are generally responding to reviews." if st == PASS else ("You are responding to some reviews." if st == WARN else "You are rarely responding to reviews."), WHAT_L["response"], HOW_L["response"], [f"{len(responded)} of {len(recent)} recent reviews responded to"], priority=MED, weight=2, rec_title="Respond to every review"))
        neg = [rv for rv in recent if (rv.get("rating") or 5) <= 3]
        negr = [rv for rv in neg if rv.get("response")]
        st = PASS if len(negr) == len(neg) else (WARN if negr else FAIL)
        c.append(Check("negative", "All Negative Reviews Responded To", st, "You have responded to all recent Negative Reviews." if st == PASS else "Some recent Negative Reviews have not been responded to.", WHAT_L["negative"], HOW_L["negative"], [f"{len(negr)} of {len(neg)} recent negative reviews responded to"], priority=HIGH if st == FAIL else MED, weight=2, rec_title="Respond to negative reviews"))
        good = [rv for rv in recent if (rv.get("rating") or 0) >= 4 and rv.get("snippet")][:3]
        if good:
            c.append(Check("recent_good", "Recent Good Reviews", INFO, "", kind="reviewcards", extra={"reviews": [{"stars": _stars(rv["rating"]), "date": rv.get("date"), "text": rv["snippet"][:260]} for rv in good]}))
    return c


def gbp_post_checks(d: dict) -> list[Check]:
    g = d["external"].get("gbp", {})
    det = g.get("details") or {}
    posts = det.get("posts")
    if posts is None or not (g.get("available") and g.get("found")):
        return [Check("posts_none", "Posts", INFO, "", hide=True)]
    c: list[Check] = []
    c.append(Check("posts", "Posts in Use", PASS if posts else FAIL, "Your business is making use of Posts." if posts else "Your business is not making use of Posts.", WHAT_L["posts"], HOW_L["posts"], [f"{len(posts)} recent posts found"] if posts else [], priority=MED, weight=2, rec_title="Start publishing GBP Posts"))
    if posts:
        c.append(Check("recent_posts", "Recent Posts", INFO, "", kind="postcards", extra={"posts": posts[:6]}))
    return c
