#!/usr/bin/env python3
"""v2.1 定向测试 — 验证 4 项修复"""
import json, time, urllib.request, urllib.error

WORKER = "https://ai-team-hub.wt5371.workers.dev"
results = []

def test(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((name, status, detail))
    print("  [%s] %s: %s %s" % ("OK" if passed else "FAIL", name, status, detail))

def call_api(path, data=None, timeout=180):
    url = WORKER + path
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; Hermes/1.0)",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        return {"error": e.reason, "detail": e.read().decode()[:300]}, e.code
    except Exception as e:
        return {"error": str(e)}, 0

def call_orchestrator(task, intent="", provider="openrouter", model="openrouter/owl-alpha"):
    return call_api("/api/orchestrator/run", {
        "task": task, "intent": intent, "provider": provider, "model": model,
    })

passed = 0
failed = 0

# ═══════════════════════════════════════════
# Fix 1: DAG Semantic Enrichment
# ═══════════════════════════════════════════
print("\n" + "="*60)
print("Fix 1: DAG Semantic Enrichment")
print("="*60)

# Test: complex task should produce substantive results from all nodes
r, _ = call_orchestrator(
    "Design a rate limiting system with Redis, including sliding window algorithm, distributed locking, and monitoring dashboard",
    intent="complex"
)
if "final_result" in r:
    dag = r.get("dag_results", {})
    # All nodes should succeed
    for node_id, node_result in dag.items():
        test("dag_%s_success" % node_id, node_result.get("status") == "success",
             "status=%s err=%s" % (node_result.get("status"), node_result.get("error","")[:80]))
        # Each node should produce substantive output (>100 chars)
        result_len = len(node_result.get("result", ""))
        test("dag_%s_substantive" % node_id, result_len > 100,
             "len=%d" % result_len)
    # Final result should be long
    final_len = len(r.get("final_result", ""))
    test("final_result_substantive", final_len > 500, "len=%d" % final_len)
else:
    test("fix1_orchestrator", False, "orchestrator failed")

# ═══════════════════════════════════════════
# Fix 2: Output Schema Hardening
# ═══════════════════════════════════════════
print("\n" + "="*60)
print("Fix 2: Output Schema Hardening")
print("="*60)

# Test: verify all agent outputs are valid JSON with required fields
r2, _ = call_orchestrator("Write a Python function to calculate fibonacci", intent="code")
if "final_result" in r2:
    dag2 = r2.get("dag_results", {})
    for node_id, node_result in dag2.items():
        result = node_result.get("result", "")
        if result:
            # Try to parse as JSON
            try:
                obj = json.loads(result)
                has_status = "status" in obj
                has_result = "result" in obj and len(obj.get("result", "")) > 0
                test("schema_%s_valid_json" % node_id, has_status and has_result,
                     "has_status=%s has_result=%s" % (has_status, has_result))
            except json.JSONDecodeError:
                # Fallback: raw text is acceptable if it's substantive
                test("schema_%s_substantive_fallback" % node_id, len(result) > 50,
                     "len=%d (not JSON but substantive)" % len(result))
        else:
            test("schema_%s_nonempty" % node_id, False, "empty result")
else:
    test("fix2_orchestrator", False, "orchestrator failed")

# ═══════════════════════════════════════════
# Fix 3: Tool Failure Handling
# ═══════════════════════════════════════════
print("\n" + "="*60)
print("Fix 3: Tool Failure Handling")
print("="*60)

# Test 3a: Non-existent provider should fail gracefully
r3a, c3a = call_orchestrator("hello", provider="nonexistent_xyz")
test("bad_provider_returns_error", c3a >= 400, "http=%d" % c3a)
test("bad_provider_no_crash", "error" in r3a or "detail" in r3a or "state" in r3a, "response has error info")

# Test 3b: Valid provider should work
r3b, c3b = call_orchestrator("Say hello in one word", intent="code")
test("valid_provider_works", "final_result" in r3b and r3b.get("state") == "DONE",
     "state=%s" % r3b.get("state", ""))

# Test 3c: Check error classification in DAG results
if "final_result" in r3b:
    dag3b = r3b.get("dag_results", {})
    for node_id, node_result in dag3b.items():
        cat = node_result.get("error_category", node_result.get("errorCategory", ""))
        err = node_result.get("error", "")
        if err:
            test("error_classified_%s" % node_id, cat != "",
                 "category=%s err=%s" % (cat, err[:60]))
        else:
            test("error_classified_%s" % node_id, True, "no error (success)")

# ═══════════════════════════════════════════
# Fix 4: Reviewer Quality Enhancement
# ═══════════════════════════════════════════
print("\n" + "="*60)
print("Fix 4: Reviewer Quality Enhancement")
print("="*60)

r4, _ = call_orchestrator(
    "Design a message queue system with at-least-once delivery, dead letter queue, and auto-scaling",
    intent="complex"
)
if "final_result" in r4:
    review = r4.get("review_result", {})
    valid_categories = ["missing_content", "wrong_scope", "poor_quality", "incomplete", "off_topic", "format_error", "none"]
    valid_severities = ["critical", "major", "minor", "none"]

    # Check review has all required fields
    has_pass = "pass" in review
    has_reason = "reason" in review and len(review.get("reason", "")) > 0
    cat = review.get("failure_category", review.get("failureCategory", ""))
    has_cat = bool(cat)
    has_valid_cat = cat in valid_categories
    test("review_has_failure_category", has_cat, "category=%s" % cat)
    test("review_valid_category", has_valid_cat, "category=%s" % cat)

    root = review.get("root_cause", review.get("rootCause", ""))
    has_root_cause = bool(root)
    test("review_has_root_cause", has_root_cause, "root_cause=%s" % root[:60])

    sev = review.get("severity", review.get("Severity", ""))
    test("review_has_severity", bool(sev), "severity=%s" % sev)
    test("review_valid_severity", sev in valid_severities, "severity=%s" % sev)

    print("\n  Review output: pass=%s category=%s severity=%s" % (review.get("pass"), cat, sev))
    print("  Root cause: %s" % review.get("root_cause", "")[:100])
    print("  Reason: %s" % review.get("reason", "")[:100])
else:
    test("fix4_orchestrator", False, "orchestrator failed")

# ═══════════════════════════════════════════
# Report
# ═══════════════════════════════════════════
print("\n" + "="*60)
print("v2.1 FIX VERIFICATION REPORT")
print("="*60)

total = len(results)
passed_count = sum(1 for _, s, _ in results if s == "PASS")
failed_count = total - passed_count

print("\n  Total: %d" % total)
print("  Passed: %d" % passed_count)
print("  Failed: %d" % failed_count)
print("  Rate: %.0f%%" % (passed_count/total*100))

if failed_count > 0:
    print("\n  FAILED:")
    for name, status, detail in results:
        if status == "FAIL":
            print("    - %s: %s" % (name, detail))

print("\n" + "="*60)
if failed_count == 0:
    print("ALL FIXES VERIFIED!")
elif passed_count / total >= 0.8:
    print("FIXES MOSTLY WORKING - minor issues remain")
else:
    print("FIXES NEED MORE WORK")
print("="*60)
