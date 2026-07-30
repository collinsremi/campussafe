import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import request as urllib_request

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
GEMMA_MODEL = "gemma-3-27b-it"


# =============================================================================
# SHARED STATE — this file (data.json) is the one source of truth for every
# visitor. Previously this app used the browser's localStorage, which meant
# every visitor had their own private copy and never saw anyone else's
# reports. That defeats the entire purpose of a shared safety board, so all
# reads and writes now go through here instead.
# =============================================================================

INITIAL_STATE = {
    "restaurants": [
        {"id": 1, "name": "The Green Table", "campus": "North Hall", "rating": 4.8, "safety": "Safe", "reports": 2, "score": 92, "alerts": 0},
        {"id": 2, "name": "Crisp Bites", "campus": "Library Quad", "rating": 4.2, "safety": "Watch", "reports": 5, "score": 74, "alerts": 2},
        {"id": 3, "name": "Noodle House", "campus": "Engineering Block", "rating": 3.9, "safety": "Alert", "reports": 8, "score": 61, "alerts": 4},
        {"id": 4, "name": "Sunset Grill", "campus": "Student Center", "rating": 4.7, "safety": "Safe", "reports": 1, "score": 95, "alerts": 0}
    ],
    "reports": [
        {"id": 1, "restaurantId": 2, "restaurant": "Crisp Bites", "concern": "Food poisoning", "severity": "High", "details": "Several students reported nausea after the evening special.", "time": "12m ago", "status": "pending"},
        {"id": 2, "restaurantId": 3, "restaurant": "Noodle House", "concern": "Cold storage", "severity": "Medium", "details": "A staff member noted that dumplings were left out too long.", "time": "43m ago", "status": "reviewed"},
        {"id": 3, "restaurantId": 1, "restaurant": "The Green Table", "concern": "Poor hygiene", "severity": "Low", "details": "Cutlery station lacked regular sanitizing.", "time": "1h ago", "status": "pending"}
    ]
}


def read_state():
    with DATA_LOCK:
        if not DATA_PATH.exists():
            DATA_PATH.write_text(json.dumps(INITIAL_STATE, indent=2), encoding="utf-8")
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def write_state(state):
    with DATA_LOCK:
        DATA_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def recompute_safety(restaurant):
    restaurant["safety"] = "Safe" if restaurant["score"] >= 85 else "Watch" if restaurant["score"] >= 70 else "Alert"


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
    api_key = os.getenv("GEMMA_API_KEY") or ENV_VALUES.get("GEMMA_API_KEY", "")
    return {
        "enabled": bool(api_key),
        "apiKeyPresent": bool(api_key),
        "model": GEMMA_MODEL,
    }


def get_api_key():
    return os.getenv("GEMMA_API_KEY") or ENV_VALUES.get("GEMMA_API_KEY", "")


# =============================================================================
# GEMMA FUNCTION CALLING — the assistant used to paste the entire reports
# and restaurants arrays into the prompt as raw JSON on every question. That
# works for a tiny demo dataset, but it's not real integration: Gemma wasn't
# deciding what data it needed, we were force-feeding all of it every time.
# These two tools let Gemma pull only what it decides is relevant.
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
    ranked = sorted(state["restaurants"], key=lambda r: r["score"])[:3]
    return {"hotspots": [{"name": r["name"], "score": r["score"], "campus": r["campus"]} for r in ranked]}


def call_gemma_api(contents, tools=None):
    api_key = get_api_key()
    if not api_key:
        return None
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMMA_MODEL}:generateContent?key={api_key}"
    payload = {"contents": contents, "generationConfig": {"temperature": 0.2}}
    if tools:
        payload["tools"] = tools

    req = urllib_request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def extract_text(body):
    if not body:
        return ""
    candidates = body.get("candidates") or []
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts") or []
    return " ".join(p.get("text", "") for p in parts if p.get("text"))


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
    hotspot_names = [restaurant.get("name") for restaurant in sorted(restaurants, key=lambda item: item.get("score", 100))[:3]]
    urgent_details = [
        f"{item.get('restaurant', 'unknown')} ({item.get('concern', 'concern')} • {item.get('severity', 'unknown')})"
        for item in urgent_reports[:3]
    ]
    if "risk" in prompt_lower or "urgent" in prompt_lower:
        return (
            f"The most urgent signals are {', '.join(urgent_details) or 'no active urgent reports'} with {len(urgent_reports)} active high/medium severity items. "
            f"The lowest-scoring venues are {', '.join(hotspot_names)}."
        )
    if "recommend" in prompt_lower or "next" in prompt_lower or "what should" in prompt_lower:
        return (
            f"I recommend prioritizing review for {urgent_details[0] if urgent_details else 'the highest-risk venue'} first, then checking the remaining open reports and escalating any new high-severity incidents."
        )
    return (
        f"I reviewed {len(open_reports)} active reports and found the strongest concerns around {', '.join(urgent_details) or 'the current campus feed'}. "
        f"The riskiest venues currently appear to be {', '.join(hotspot_names)}."
    )


def query_gemma(prompt, state):
    if not get_api_key():
        return None

    system_text = (
        "You are CampusSafe AI, helping review a campus food-safety board. "
        f"Question: {prompt}\n"
        "Call get_recent_reports_for_restaurant if the question is about a specific place, "
        "or get_hotspots if it's about overall risk, before answering. Keep the final answer to 2-4 sentences."
    )
    contents = [{"role": "user", "parts": [{"text": system_text}]}]

    first = call_gemma_api(contents, tools=TOOLS)
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
        second = call_gemma_api(follow_up_contents)
        text = extract_text(second)
    else:
        text = extract_text(first)

    if not text:
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
                result = {"answer": build_fallback_response(prompt, state["reports"], state["restaurants"]), "source": "fallback"}
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
            if new_report["severity"] == "High":
                restaurant["score"] = max(30, restaurant["score"] - 12)
                restaurant["alerts"] += 1
            elif new_report["severity"] == "Medium":
                restaurant["score"] = max(30, restaurant["score"] - 6)
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
                restaurant["score"] = max(20, restaurant["score"] - 10)
                restaurant["alerts"] += 1
            elif action == "dismiss":
                report["status"] = "dismissed"
            recompute_safety(restaurant)

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
    server.serve_forever()
