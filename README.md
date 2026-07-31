# CampusSafe

**Live app:** [campussafe.onrender.com](https://campussafe.onrender.com)


A shared food-safety board for campus life. Students report food poisoning,
hygiene issues, or unsafe storage at campus restaurants; admins review and
escalate; Gemma helps surface patterns and answer safety questions across
the live data.

Built for the Build with Gemma: AI for Africa Hackathon.

## Features

- Live safety board with per-restaurant status: **Unrated** until the first
  report comes in, then **Safe / Watch / Alert** based on accumulated risk
  from actual reports — no restaurant starts with an assumed score
- Real GK restaurants seeded on launch: Unique Kitchen, Mama Abbas,
  Pop Area, Asadel, Food Republic, Delight — plus a "Register a restaurant"
  flow so admins can add more without touching code
- Student incident reporting (concern type, severity, details)
- Admin review queue — approve, escalate, or dismiss reports
- Campus-wide analytics: active reports, hotspots, response time, top concern patterns
- Floating chat assistant (bottom-right) powered by Gemma with function
  calling — it decides whether to pull recent reports for a specific
  restaurant or the current campus-wide hotspots before answering, and
  keeps a running conversation instead of overwriting a single response box.
  If the Gemma call fails for any reason (missing/invalid key, quota,
  network), the server logs the exact HTTP error to its console and the
  assistant falls back to a local rule-based summary instead of breaking
- Shared state across all users — no login required, no per-browser data silos

## Tech stack

- Vanilla HTML/CSS/JS frontend
- Python standard-library HTTP server (no framework, no dependencies)
- Google Gemma API (via Google AI Studio) for the assistant, with tool/function calling
- JSON file storage for shared app state

## Getting started

```bash
git clone https://github.com/<your-username>/campussafe.git
cd campussafe
python3 server.py
```

Open `http://localhost:8000`.

Create a `.env` file in the project root with your Gemma API key:

```
GEMMA_API_KEY=your_key_here
```

Get a free key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
Without a key, the assistant falls back to a local rule-based summary
instead of failing.

## Deployment

This is a lightweight Python server — deploy it anywhere that runs a
process (Render, Railway, Fly.io). Example using Render:

1. Push this repo to GitHub
2. On [render.com](https://render.com): **New → Web Service** → connect the repo
3. Start command: `python3 server.py`
4. Add environment variable `GEMMA_API_KEY`
5. Deploy

The server reads the `PORT` environment variable automatically, so no
config changes are needed for most hosts.

## Project structure

```
campussafe/
├── index.html          # UI
├── styles.css           # styling
├── app.js               # frontend logic, talks to the API
├── server.py             # backend — state, review actions, Gemma integration
├── test_server.py        # backend tests
└── .gitignore
```

## API

| Endpoint | Method | Description |
|---|---|---|
| `/api/state` | GET | Current restaurants and reports |
| `/api/reports` | POST | Submit a new incident report |
| `/api/reports/<id>/review` | POST | Approve, escalate, or dismiss a report |
| `/api/restaurants` | POST | Register a new restaurant onto the shared board |
| `/api/assistant` | POST | Ask Gemma a safety question |
| `/api/config` | GET | Current model/config status |

## Scoring model

A restaurant's `score` is accumulated risk, not remaining trust — every
restaurant starts at **0** with no history. Reports push it up by severity
(Low +5, Medium +15, High +30, capped at 100); escalating a report adds
+15, dismissing one removes 10. Status is derived from that:

| Reports | Score | Status |
|---|---|---|
| 0 | — | Unrated |
| >0 | < 25 | Safe |
| >0 | 25–54 | Watch |
| >0 | ≥ 55 | Alert |

A restaurant with zero reports is Unrated, not Safe and not Alert — there's
just no data yet, and that's a meaningfully different claim to make about
a real business.

## Debugging the assistant

If a response ever looks like raw reasoning instead of a clean answer
(long, rambling, talking about what tool to call rather than just calling
it), check the server console — `query_gemma()` discards anything that
matches that pattern and falls back automatically, logging why. This
project explicitly disables the model's visible thinking via
`thinkingConfig` and filters out any `"thought": true` parts from the
response, so it shouldn't happen, but the guard is there either way.

If `/api/assistant` keeps returning `"source": "fallback"`, run the server
in a terminal (`python3 server.py`) and ask a question — any failed Gemma
call is logged there with the real reason (e.g. an HTTP 400/403 from
Google, a bad model name, or no key found). Note that Google AI Studio
keys now default to the newer `AQ.` "auth key" format rather than the
older `AIza...` "standard key" format — either can be valid, so don't
assume a key is bad just because it starts with `AQ.`. This project talks
to Gemma 4 (`gemma-4-26b-a4b-it`); if you're on an older clone that still
references `gemma-3-27b-it`, update `GEMMA_MODEL` in `server.py`.

## Roadmap

- Formal complaint drafting for direct handoff to Student Affairs / campus health
- Emergency-symptom guardrail for severe reports
- Photo evidence support (multimodal)
- Role-based access for admin actions
- Anonymous reporting option

- Role-based access for admin actions
- Anonymous reporting option
