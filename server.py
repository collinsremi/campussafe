import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import request as urllib_request
from urllib import error as urllib_error

ROOT = Path(__file__).parent.resolve()
ENV_PATH = ROOT / ".env"
DATA_PATH = ROOT / "data.json"
DATA_LOCK = threading.Lock()


def load_env_file():
    env = {}
    if not ENV_PATH.exists():
        return env
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


ENV_VALUES = load_env_file()

# Single source of truth for the model — confirm the exact current string
# in your Google AI Studio model picker before you submit. Everything else
# in this file reads from this constant so the /api/config response and the
# actual API call can never silently drift apart again.
#
# Gemma 3 is not what's served under this name anymore — Gemma 4 shipped
# April 2026, and the hosted Gemini API only exposes two Gemma 4 model
# ids: "gemma-4-31b-it" and "gemma-4-26b-a4b-it" (the lower-latency MoE
# variant, and the one Google's own docs use as the default example).
GEMMA_MODEL = "gemma-4-26b-a4b-it"


# =============================================================================
# SHARED STATE — this file (data.json) is the one source of truth for every
# visitor. Reads and writes all go through here so every visitor sees the
# same restaurants and reports instead of a private per-browser copy.
#
# Seed data below is the real FUT Minna restaurant set — swap in more, or
# let admins add them live via "Register a restaurant" in the UI, which
# posts to /api/restaurants and appends to this same file.
# =============================================================================

INITIAL_STATE = {
    "restaurants": [
        {"id": 1, "name": "Unique Kitchen", "campus": "GK", "rating": 0, "safety": "Unrated", "reports": 0, "score": 0, "alerts": 0, "remarks": {"positive": 0, "negative": 0}},
        {"id": 2, "name": "Mama Abbas", "campus": "GK", "rating": 0, "safety": "Unrated", "reports": 0, "score": 0, "alerts": 0, "remarks": {"positive": 0, "negative": 0}},
        {"id": 3, "name": "Pop Area", "campus": "GK", "rating": 0, "safety": "Unrated", "reports": 0, "score": 0, "alerts": 0, "remarks": {"positive": 0, "negative": 0}},
        {"id": 4, "name": "Asadel", "campus": "GK", "rating": 0, "safety": "Unrated", "reports": 0, "score": 0, "alerts": 0, "remarks": {"positive": 0, "negative": 0}},
        {"id": 5, "name": "Food Republic", "campus": "GK", "rating": 0, "safety": "Unrated", "reports": 0, "score": 0, "alerts": 0, "remarks": {"positive": 0, "negative": 0}},
        {"id": 6, "name": "Delight", "campus": "GK", "rating": 0, "safety": "Unrated", "reports": 0, "score": 0, "alerts": 0, "remarks": {"positive": 0, "negative": 0}}
    ],
    "reports": []
}


def read_state():
    with DATA_LOCK:
        if not DATA_PATH.exists():
            DATA_PATH.write_text(json.dumps(INITIAL_STATE, indent=2), encoding="utf-8")
        state = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        # Back-fill remarks for restaurants saved before this field existed,
        # so an older data.json on disk doesn't break the remark UI.
        for restaurant in state.get("restaurants", []):
            restaurant.setdefault("remarks", {"positive": 0, "negative": 0})
        return state


def write_state(state):
    with DATA_LOCK:
        DATA_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


# Score now means accumulated risk, not remaining trust: every restaurant
# starts at 0 with no history, and reports push it up as evidence comes in.
# A restaurant with zero reports is "Unrated" — it hasn't earned an Alert
# any more than it's earned a Safe; there's just no data yet, and that's a
# meaningfully different thing to say about a real business.
SEVERITY_RISK_WEIGHT = {"High": 30, "Medium": 15, "Low": 5}


def recompute_safety(restaurant):
    if restaurant["reports"] == 0:
        restaurant["safety"] = "Unrated"
    elif restaurant["score"] < 25:
        restaurant["safety"] = "Safe"
    elif restaurant["score"] < 55:
        restaurant["safety"] = "Watch"
    else:
        restaurant["safety"] = "Alert"


def get_content_type(path: str) -> str:
    if path.endswith(".html"):
        return "text/html; charset=utf-8"
    if path.endswith(".css"):
        return "text/css; charset=utf-8"
    if path.endswith(".js"):
        return "application/javascript; charset=utf-8"
    if path.endswith(".json"):
        return "application/json; charset=utf-8"
    if path.endswith(".png"):
        return "image/png"
    if path.endswith(".jpg") or path.endswith(".jpeg"):
        return "image/jpeg"
    if path.endswith(".svg"):
        return "image/svg+xml"
    return "application/octet-stream"


def get_config():
    api_key = get_api_key()
    return {
        "enabled": bool(api_key),
        "apiKeyPresent": bool(api_key),
        "model": GEMMA_MODEL,
        "lastError": LAST_GEMMA_ERROR,
    }


def get_api_key():
    return os.getenv("GEMMA_API_KEY") or ENV_VALUES.get("GEMMA_API_KEY", "")


# Set by call_gemma_api whenever a call fails, cleared on success. Exposed
# via /api/config and echoed onto the fallback response so the *why* is
# visible from the browser/deployed app, not just a terminal you may not
# have open (e.g. on Render/Railway).
LAST_GEMMA_ERROR = None


# =============================================================================
# GEMMA FUNCTION CALLING — the assistant doesn't get the raw reports/
# restaurants arrays dumped into the prompt. It gets two tools and decides
# for itself whether it needs per-restaurant reports or campus-wide
# hotspots before it answers, then a second call produces the final text.
#
# If GEMMA_API_KEY is missing, unauthorized, or the request otherwise
# fails, call_gemma_api logs *why* to stderr AND stores it in
# LAST_GEMMA_ERROR, then returns None so the caller falls back to
# build_fallback_response. That fallback existing is correct — it means
# the product still works if Google's API has a bad minute — but if you
# keep landing on it, check /api/config or the assistant's status line
# in the UI for the real reason. Note: keys starting with "AQ." are
# current Google AI Studio "auth keys" (the new default, replacing the
# older "AIza..." standard-key format) — that prefix alone doesn't mean a
# key is bad.
# =============================================================================

TOOLS = [{
    "functionDeclarations": [
        {
            "name": "get_recent_reports_for_restaurant",
            "description": "Get recent safety reports filed against a specific restaurant.",
            "parameters": {
                "type": "OBJECT",
                "properties": {"restaurant": {"type": "STRING", "description": "Name of the restaurant"}},
                "required": ["restaurant"]
            }
        },
        {
            "name": "get_hotspots",
            "description": "Get the current lowest safety-scoring restaurants campus-wide.",
            "parameters": {"type": "OBJECT", "properties": {}}
        }
    ]
}]


def tool_get_recent_reports_for_restaurant(state, restaurant_name):
    name = (restaurant_name or "").lower()
    matches = [r for r in state["reports"] if name in r["restaurant"].lower() or r["restaurant"].lower() in name]
    return {"restaurant": restaurant_name, "matching_reports": matches[:5]}


def tool_get_hotspots(state):
    rated = [r for r in state["restaurants"] if r["reports"] > 0]
    ranked = sorted(rated, key=lambda r: r["score"], reverse=True)[:3]
    return {"hotspots": [{"name": r["name"], "score": r["score"], "campus": r["campus"]} for r in ranked]}


def call_gemma_api(contents, tools=None, system_instruction=None):
    global LAST_GEMMA_ERROR
    api_key = get_api_key()
    if not api_key:
        LAST_GEMMA_ERROR = "No GEMMA_API_KEY found in environment or .env"
        print(f"[gemma] {LAST_GEMMA_ERROR} — using fallback")
        return None

    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMMA_MODEL}:generateContent"

    def build_payload(include_thinking_config):
        generation_config = {"temperature": 0.2}
        if include_thinking_config:
            # thinkingBudget: 0 asks the model to skip visible chain-of-thought
            # entirely. Not every Gemma model/API version accepts this field —
            # if it gets rejected, attempt_request() below retries without it
            # rather than letting every single call fail.
            generation_config["thinkingConfig"] = {"thinkingBudget": 0}
        payload = {"contents": contents, "generationConfig": generation_config}
        if tools:
            payload["tools"] = tools
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        return payload

    def attempt_request(include_thinking_config):
        req = urllib_request.Request(
            endpoint,
            data=json.dumps(build_payload(include_thinking_config)).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            method="POST",
        )
        with urllib_request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        result = attempt_request(True)
        LAST_GEMMA_ERROR = None
        return result
    except urllib_error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8")
        except Exception:
            detail = "<no body>"

        if e.code == 400:
            # Most likely cause of a 400 here is thinkingConfig itself not
            # being recognized by this model — retry once without it before
            # giving up, so a live answer still comes through.
            print(f"[gemma] HTTP 400 with thinkingConfig ({detail[:200]}) — retrying without it")
            try:
                result = attempt_request(False)
                LAST_GEMMA_ERROR = None
                return result
            except urllib_error.HTTPError as e2:
                try:
                    detail2 = e2.read().decode("utf-8")
                except Exception:
                    detail2 = "<no body>"
                LAST_GEMMA_ERROR = f"HTTP {e2.code} calling {GEMMA_MODEL}: {detail2}"
                print(f"[gemma] {LAST_GEMMA_ERROR}")
                return None

        # This is the one that matters most for any other failure: it tells
        # you *why* Gemma rejected the call (bad key, wrong model name, quota).
        LAST_GEMMA_ERROR = f"HTTP {e.code} calling {GEMMA_MODEL}: {detail}"
        print(f"[gemma] {LAST_GEMMA_ERROR}")
        return None
    except urllib_error.URLError as e:
        LAST_GEMMA_ERROR = f"Network error calling Gemma API: {e.reason}"
        print(f"[gemma] {LAST_GEMMA_ERROR}")
        return None
    except Exception as e:
        LAST_GEMMA_ERROR = f"Unexpected error calling Gemma API: {e}"
        print(f"[gemma] {LAST_GEMMA_ERROR}")
        return None


def extract_text(body):
    if not body:
        return ""
    candidates = body.get("candidates") or []
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts") or []
    # Thinking-capable models return reasoning as separate parts marked
    # "thought": true. Joining those in with the real answer is exactly
    # what was leaking raw chain-of-thought into the UI — only the
    # non-thought parts are the actual answer.
    return " ".join(p.get("text", "") for p in parts if p.get("text") and not p.get("thought"))


REASONING_LEAK_MARKERS = (
    "the user provided", "let me", "let's", "i should", "wait,", "i'll just",
    "i need to", "hmm,", "as an ai", "i'll respond", "actually, i'll"
)


def looks_like_leaked_reasoning(text):
    # Belt-and-suspenders on top of the thought-part filtering above: if a
    # response still reads like internal deliberation (multiple planning
    # phrases, or just unreasonably long for a 2-4 sentence answer), treat
    # it as unusable rather than show it to a student or admin.
    lowered = text.lower()
    hits = sum(1 for marker in REASONING_LEAK_MARKERS if marker in lowered)
    return hits >= 2 or len(text) > 700


def extract_function_call(body):
    if not body:
        return None
    candidates = body.get("candidates") or []
    if not candidates:
        return None
    parts = candidates[0].get("content", {}).get("parts") or []
    for p in parts:
        if p.get("functionCall"):
            return p["functionCall"]
    return None


def build_fallback_response(prompt, reports, restaurants):
    prompt_lower = (prompt or "").lower()
    open_reports = [report for report in reports if report.get("status") != "dismissed"]
    urgent_reports = [report for report in open_reports if report.get("severity") in {"High", "Medium"}]
    rated = [r for r in restaurants if r.get("reports", 0) > 0]
    hotspot_names = [r.get("name") for r in sorted(rated, key=lambda item: item.get("score", 0), reverse=True)[:3]]
    hotspot_text = ', '.join(hotspot_names) if hotspot_names else "none yet — no restaurant has an active report"
    urgent_details = [
        f"{item.get('restaurant', 'unknown')} ({item.get('concern', 'concern')} • {item.get('severity', 'unknown')})"
        for item in urgent_reports[:3]
    ]
    if "risk" in prompt_lower or "urgent" in prompt_lower:
        return (
            f"The most urgent signals are {', '.join(urgent_details) or 'no active urgent reports'} with {len(urgent_reports)} active high/medium severity items. "
            f"The highest-risk venues right now are {hotspot_text}."
        )
    if "recommend" in prompt_lower or "next" in prompt_lower or "what should" in prompt_lower:
        return (
            f"I recommend prioritizing review for {urgent_details[0] if urgent_details else 'the highest-risk venue'} first, then checking the remaining open reports and escalating any new high-severity incidents."
        )
    return (
        f"I reviewed {len(open_reports)} active reports and found the strongest concerns around {', '.join(urgent_details) or 'the current campus feed'}. "
        f"The highest-risk venues right now are {hotspot_text}."
    )


def query_gemma(prompt, state):
    global LAST_GEMMA_ERROR
    if not get_api_key():
        LAST_GEMMA_ERROR = "No GEMMA_API_KEY found in environment or .env"
        return None

    system_instruction = (
        "You are CampusSafe AI, an assistant embedded in a campus food-safety review board. "
        "Before answering, call get_recent_reports_for_restaurant if the question names a specific "
        "place, or get_hotspots if it's about overall campus risk. "
        "If the person's message is short or ambiguous — a single word, a partial name, something "
        "that doesn't look like a full sentence — treat it as an attempted restaurant name and call "
        "get_recent_reports_for_restaurant with it directly rather than asking for clarification. "
        "Only ask a clarifying question if it's truly not a plausible restaurant name and not a "
        "campus-risk question either. "
        "Respond with ONLY your final answer: 2-4 concrete sentences, grounded solely in the tool "
        "data you receive, never inventing incidents. Never show your reasoning, planning, or "
        "internal deliberation — no phrases like 'let me', 'I should', or 'wait' — just the answer."
    )
    contents = [{"role": "user", "parts": [{"text": prompt}]}]

    first = call_gemma_api(contents, tools=TOOLS, system_instruction=system_instruction)
    if first is None:
        return None

    fn_call = extract_function_call(first)
    if fn_call:
        name = fn_call.get("name")
        args = fn_call.get("args", {})
        if name == "get_recent_reports_for_restaurant":
            result = tool_get_recent_reports_for_restaurant(state, args.get("restaurant"))
        elif name == "get_hotspots":
            result = tool_get_hotspots(state)
        else:
            result = {"note": "Unknown tool requested."}

        follow_up_contents = contents + [
            {"role": "model", "parts": [{"functionCall": fn_call}]},
            {"role": "user", "parts": [{"functionResponse": {"name": name, "response": {"result": result}}}]},
            {"role": "user", "parts": [{"text": "Now give your final answer, 2-4 sentences."}]}
        ]
        second = call_gemma_api(follow_up_contents, system_instruction=system_instruction)
        text = extract_text(second)
    else:
        text = extract_text(first)

    if not text:
        LAST_GEMMA_ERROR = "Gemma call succeeded but returned no usable text (empty response or unhandled tool call)"
        print(f"[gemma] {LAST_GEMMA_ERROR} — falling back")
        return None
    if looks_like_leaked_reasoning(text):
        LAST_GEMMA_ERROR = "Gemma response looked like leaked reasoning rather than a final answer — discarded"
        print(f"[gemma] {LAST_GEMMA_ERROR}: {text[:200]}...")
        return None
    return {"answer": text.strip(), "source": "gemma"}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path == "/api/config":
            self.send_json(get_config())
            return

        if path == "/api/state":
            self.send_json(read_state())
            return

        if path in {"/", ""}:
            path = "/index.html"

        file_path = ROOT / path.lstrip("/")
        if file_path.exists() and file_path.is_file():
            content = file_path.read_bytes()
            content_type = get_content_type(file_path.name)
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        self.send_error(404, "Not Found")

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/assistant":
            data = self._read_json_body()
            prompt = data.get("prompt", "")
            state = read_state()
            result = query_gemma(prompt, state)
            if not result:
                result = {
                    "answer": build_fallback_response(prompt, state["reports"], state["restaurants"]),
                    "source": "fallback",
                    "debug": LAST_GEMMA_ERROR,
                }
            self.send_json(result)
            return

        if path == "/api/reports":
            data = self._read_json_body()
            state = read_state()
            restaurant = next((r for r in state["restaurants"] if r["id"] == data.get("restaurantId")), None)
            if not restaurant:
                self.send_json({"error": "Unknown restaurant"}, status=400)
                return

            new_report = {
                "id": int(time.time() * 1000),
                "restaurantId": restaurant["id"],
                "restaurant": restaurant["name"],
                "concern": data.get("concern", "Other"),
                "severity": data.get("severity", "Low"),
                "details": (data.get("details") or "").strip() or "No extra details provided.",
                "time": "just now",
                "status": "pending"
            }
            state["reports"].insert(0, new_report)
            restaurant["reports"] += 1
            weight = SEVERITY_RISK_WEIGHT.get(new_report["severity"], 5)
            restaurant["score"] = min(100, restaurant["score"] + weight)
            if new_report["severity"] == "High":
                restaurant["alerts"] += 1
            recompute_safety(restaurant)

            write_state(state)
            self.send_json(state)
            return

        if path.startswith("/api/reports/") and path.endswith("/review"):
            report_id = int(path.split("/")[3])
            data = self._read_json_body()
            action = data.get("action")

            state = read_state()
            report = next((r for r in state["reports"] if r["id"] == report_id), None)
            restaurant = next((r for r in state["restaurants"] if r["id"] == (report or {}).get("restaurantId")), None)
            if not report or not restaurant:
                self.send_json({"error": "Report not found"}, status=404)
                return

            if action == "approve":
                report["status"] = "reviewed"
            elif action == "escalate":
                report["status"] = "escalated"
                restaurant["score"] = min(100, restaurant["score"] + 15)
                restaurant["alerts"] += 1
            elif action == "dismiss":
                report["status"] = "dismissed"
                restaurant["score"] = max(0, restaurant["score"] - 10)
            recompute_safety(restaurant)

            write_state(state)
            self.send_json(state)
            return

        if path == "/api/restaurants":
            # Onboarding: lets an admin register a new campus restaurant
            # straight from the UI instead of editing seed data by hand.
            # It joins the same shared board everyone else sees.
            data = self._read_json_body()
            name = (data.get("name") or "").strip()
            campus = (data.get("campus") or "").strip()
            if not name or not campus:
                self.send_json({"error": "Name and campus location are required"}, status=400)
                return

            state = read_state()
            if any(r["name"].strip().lower() == name.lower() for r in state["restaurants"]):
                self.send_json({"error": "That restaurant is already on the board"}, status=409)
                return

            next_id = max((r["id"] for r in state["restaurants"]), default=0) + 1
            new_restaurant = {
                "id": next_id,
                "name": name,
                "campus": campus,
                "rating": 0,
                "safety": "Unrated",
                "reports": 0,
                "score": 0,
                "alerts": 0,
                "remarks": {"positive": 0, "negative": 0}
            }
            state["restaurants"].append(new_restaurant)
            write_state(state)
            self.send_json(state)
            return

        if path.startswith("/api/restaurants/") and path.endswith("/remark"):
            # Good/bad remarks are deliberately separate from the formal
            # incident-report pipeline above: this is lightweight community
            # sentiment ("service was great" / "meh today"), not a safety
            # claim, so it never touches score/safety/alerts.
            parts = path.split("/")
            try:
                restaurant_id = int(parts[3])
            except (IndexError, ValueError):
                self.send_json({"error": "Invalid restaurant id"}, status=400)
                return

            data = self._read_json_body()
            remark_type = data.get("type")
            if remark_type not in {"positive", "negative"}:
                self.send_json({"error": "type must be 'positive' or 'negative'"}, status=400)
                return

            state = read_state()
            restaurant = next((r for r in state["restaurants"] if r["id"] == restaurant_id), None)
            if not restaurant:
                self.send_json({"error": "Restaurant not found"}, status=404)
                return

            restaurant.setdefault("remarks", {"positive": 0, "negative": 0})
            restaurant["remarks"][remark_type] += 1

            write_state(state)
            self.send_json(state)
            return

        self.send_error(404, "Not Found")

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    # Render/Railway/Fly.io and most hosts assign a port via the PORT
    # environment variable — hardcoding 8000 works locally but will fail to
    # bind correctly on most free hosting platforms.
    port = int(os.environ.get("PORT", 8000))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"CampusSafe server running on http://127.0.0.1:{port}")
    print(f"[gemma] API key present: {bool(get_api_key())} — model: {GEMMA_MODEL}")
    server.serve_forever()
