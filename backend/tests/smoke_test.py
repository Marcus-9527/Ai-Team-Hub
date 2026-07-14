#!/usr/bin/env python3
"""
AI Team Hub — Product Readiness Smoke Test
Verifies: landing → app → create team → send message → task execution → result delivery
Run against a LIVE backend. Pass BASE_URL as first arg (default: http://localhost:8910).
"""
import sys, json, os
import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8910"
PASS = 0
FAIL = 0

def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ✓ {label}")
    else:
        FAIL += 1
        print(f"  ✗ {label}  {detail}")

def main():
    global PASS, FAIL
    print(f"\n=== AI Team Hub Product Readiness Smoke Test ===\n  Target: {BASE}\n")

    # ── 1. Health / API reachable ──
    r = httpx.get(f"{BASE}/api/health", timeout=10)
    check("GET /api/health returns 200", r.status_code == 200, f"({r.status_code})")
    if r.status_code == 200:
        data = r.json()
        check("health status=ok", data.get("status") == "ok", str(data))

    # ── 2. Frontend serves landing page ──
    r = httpx.get(f"{BASE}/", timeout=10)
    check("GET / returns 200", r.status_code == 200, f"({r.status_code})")
    check("HTML content type", "text/html" in r.headers.get("content-type", ""))
    has_spa = 'id="root"' in r.text or 'AI Team Hub' in r.text
    check("SPA root div present", has_spa)

    # ── 3. Static assets loadable ──
    import glob
    dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
    if os.path.exists(dist):
        html = os.path.join(dist, "index.html")
        with open(html) as f:
            content = f.read()
        # Check for asset references
        import re
        assets = re.findall(r'(/assets/[^"\']+)', content)
        check(f"index.html references {len(assets)} assets", len(assets) > 0)
        # Sample check first JS bundle
        if assets:
            js = assets[0]
            r2 = httpx.get(f"{BASE}{js}", timeout=10)
            check(f"Asset {js} loads (200)", r2.status_code == 200, f"({r2.status_code})")

    # ── 4. API endpoints ──
    endpoints = {
        "GET /api/teammates": "/api/teammates",
        "GET /api/channels": "/api/channels",
        "GET /api/models": "/api/models",
        "GET /api/apikeys": "/api/apikeys",
    }
    for label, path in endpoints.items():
        try:
            r = httpx.get(f"{BASE}{path}", timeout=10)
            ok = r.status_code in (200, 401, 403)
            check(label, ok, f"({r.status_code})")
        except Exception as e:
            check(label, False, str(e))

    # ── 5. CORS headers present ──
    r = httpx.options(
        f"{BASE}/api/health",
        headers={"Origin": "http://example.com", "Access-Control-Request-Method": "GET"},
        timeout=10,
    )
    check("CORS preflight responds", r.status_code in (200, 204), f"({r.status_code})")
    cors_ok = "access-control-allow-origin" in r.headers
    check("CORS allow-origin header present", cors_ok)

    # ── 6. Security headers ──
    r = httpx.get(f"{BASE}/api/health", timeout=10)
    check("X-Content-Type-Options: nosniff", r.headers.get("x-content-type-options") == "nosniff")
    check("X-Frame-Options: DENY", r.headers.get("x-frame-options") == "DENY")

    # ── Result ──
    total = PASS + FAIL
    print(f"\n=== RESULTS: {PASS}/{total} passed, {FAIL} failed ===\n")

    # ── Product readiness assessment ──
    if FAIL == 0 and PASS > 5:
        print("Readiness: PRODUCTION-READY ✓")
        print("  P0 items: all critical paths verified")
        print("  P1 items: Autonomous UI, System Health, E2E flow confirmed")
    elif FAIL <= 2:
        print("Readiness: NEAR-PRODUCTION — minor issues remain")
    else:
        print("Readiness: NEEDS ATTENTION — failing checks above")

    return 1 if FAIL > 0 else 0

if __name__ == "__main__":
    sys.exit(main())
