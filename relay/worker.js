/**
 * Adcraft SEO key relay. Runs on Cloudflare Workers (free tier).
 * Vendor API keys live here as Worker secrets; clients only hold RELAY_TOKEN.
 *
 * POST /ahrefs   {target}                       -> Ahrefs free Domain Rating
 * POST /opr      {domains:[...], include_history} -> OpenPageRank bulk
 * POST /serpapi  {params:{engine,q,...}}        -> SerpApi search.json
 * POST /gemini   {model, body}                  -> Gemini generateContent
 * POST /psi      {params:{url,strategy,...}}    -> PageSpeed Insights v5
 * GET  /health                                  -> which vendors are configured
 * All POSTs require:  Authorization: Bearer <RELAY_TOKEN>
 *
 * Secrets: RELAY_TOKEN, AHREFS_API_KEY, OPENPAGERANK_API_KEY, SERPAPI_API_KEY, GEMINI_API_KEY, GOOGLE_API_KEY (optional)
 * Optional var DAILY_LIMIT (default 400) caps requests per UTC day using the cache API as a soft counter.
 */
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const json = (obj, status = 200) => new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json" } });

    if (url.pathname === "/health") {
      return json({
        ok: true,
        vendors: {
          ahrefs: !!env.AHREFS_API_KEY, openpagerank: !!env.OPENPAGERANK_API_KEY, serpapi: !!env.SERPAPI_API_KEY,
          gemini: !!env.GEMINI_API_KEY, pagespeed: !!env.GOOGLE_API_KEY,
        },
      });
    }
    if (request.method !== "POST") return json({ error: "POST only" }, 405);
    const auth = request.headers.get("authorization") || "";
    if (!env.RELAY_TOKEN || auth !== `Bearer ${env.RELAY_TOKEN}`) return json({ error: "unauthorized" }, 401);

    let body;
    try { body = await request.json(); } catch { return json({ error: "invalid json" }, 400); }

    // soft daily cap (best effort; Cloudflare cache is per-colo)
    const limit = parseInt(env.DAILY_LIMIT || "400", 10);
    const day = new Date().toISOString().slice(0, 10);
    const counterKey = new Request(`https://relay.local/counter/${day}`);
    const cache = caches.default;
    let count = 0;
    const cached = await cache.match(counterKey);
    if (cached) count = parseInt(await cached.text(), 10) || 0;
    if (count >= limit) return json({ error: `daily relay limit (${limit}) reached` }, 429);
    ctx.waitUntil(cache.put(counterKey, new Response(String(count + 1), { headers: { "cache-control": "max-age=90000" } })));

    const forward = async (target, init) => {
      const r = await fetch(target, init);
      const text = await r.text();
      return new Response(text, { status: r.status, headers: { "content-type": r.headers.get("content-type") || "application/json" } });
    };

    switch (url.pathname) {
      case "/ahrefs": {
        if (!env.AHREFS_API_KEY) return json({ error: "ahrefs not configured" }, 501);
        const t = encodeURIComponent(body.target || "");
        return forward(`https://api.ahrefs.com/v3/public/domain-rating-free?target=${t}`, { headers: { Authorization: `Bearer ${env.AHREFS_API_KEY}`, Accept: "application/json" } });
      }
      case "/opr": {
        if (!env.OPENPAGERANK_API_KEY) return json({ error: "openpagerank not configured" }, 501);
        return forward("https://openpagerank.keywordseverywhere.com/v1/domains/bulk", {
          method: "POST", headers: { Authorization: `Bearer ${env.OPENPAGERANK_API_KEY}`, "content-type": "application/json" },
          body: JSON.stringify({ domains: (body.domains || []).slice(0, 100), include_history: body.include_history !== false }),
        });
      }
      case "/serpapi": {
        if (!env.SERPAPI_API_KEY) return json({ error: "serpapi not configured" }, 501);
        const p = new URLSearchParams();
        for (const [k, v] of Object.entries(body.params || {})) if (v !== undefined && v !== null) p.set(k, String(v));
        p.set("api_key", env.SERPAPI_API_KEY);
        return forward(`https://serpapi.com/search.json?${p.toString()}`, {});
      }
      case "/gemini": {
        if (!env.GEMINI_API_KEY) return json({ error: "gemini not configured" }, 501);
        const model = (body.model || "gemini-2.5-flash").replace(/[^a-z0-9.\-]/gi, "");
        return forward(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${env.GEMINI_API_KEY}`, {
          method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body.body || {}),
        });
      }
      case "/psi": {
        if (!env.GOOGLE_API_KEY) return json({ error: "pagespeed not configured" }, 501);
        const p = new URLSearchParams();
        for (const [k, v] of Object.entries(body.params || {})) {
          if (Array.isArray(v)) v.forEach((x) => p.append(k, String(x))); else if (v !== undefined && v !== null) p.set(k, String(v));
        }
        p.set("key", env.GOOGLE_API_KEY);
        return forward(`https://www.googleapis.com/pagespeedonline/v5/runPagespeed?${p.toString()}`, {});
      }
      default:
        return json({ error: "unknown endpoint" }, 404);
    }
  },
};
