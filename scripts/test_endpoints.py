"""Quick runtime endpoint test script."""
import urllib.request
import json
import sys

BASE = "http://127.0.0.1:8000"

def get(path):
    try:
        r = urllib.request.urlopen(BASE + path, timeout=10)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())
    except Exception as e:
        return 0, str(e)[:150]

def post(path, body):
    try:
        data = json.dumps(body).encode()
        req = urllib.request.Request(BASE + path, data=data, headers={"Content-Type": "application/json"})
        r = urllib.request.urlopen(req, timeout=10)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())
    except Exception as e:
        return 0, str(e)[:150]

print("=== Runtime Endpoint Tests ===")

s, b = get("/health")
print(f"GET /health -> {s}: {json.dumps(b)[:120]}")

s, b = get("/api/v1/learners")
print(f"GET /api/v1/learners -> {s}: {json.dumps(b)[:120]}")

s, b = get("/api/v1/learners/student-1/state")
found = b.get("found") if isinstance(b, dict) else "N/A"
print(f"GET /api/v1/learners/student-1/state -> {s}: found={found}")

s, b = get("/api/v1/learners/student-1/portfolio")
count = b.get("count") if isinstance(b, dict) else "N/A"
print(f"GET /api/v1/learners/student-1/portfolio -> {s}: count={count}")

s, b = get("/api/v1/calibration")
print(f"GET /api/v1/calibration -> {s}: {json.dumps(b)[:120]}")

s, b = get("/api/v1/system/agents/status")
if isinstance(b, dict):
    sm = b.get("summary", {})
    print(f"GET /api/v1/system/agents/status -> {s}: impl={sm.get('implemented','?')}/{sm.get('total_agents','?')} partial={sm.get('partial','?')} stubs={sm.get('stubs','?')}")
else:
    print(f"GET /api/v1/system/agents/status -> {s}: {b}")

s, b = post("/api/v1/events", {
    "event_id": "rt-001",
    "learner_id": "student-1",
    "event_type": "quiz_result",
    "concept_id": "algebra",
    "data": {"score": 0.75, "max_score": 1.0}
})
if isinstance(b, dict):
    action = b.get("recommended_action", "?")[:60]
    conf = b.get("confidence", "?")
    print(f"POST /api/v1/events -> {s}: action={action} confidence={conf}")
else:
    print(f"POST /api/v1/events -> {s}: {str(b)[:120]}")

# Auth endpoints (unauthenticated)
s, b = get("/auth/me")
status_str = b.get("detail", "") if isinstance(b, dict) else str(b)[:80]
print(f"GET /auth/me (no cookie) -> {s}: {status_str}")

print("\n=== Done ===")
