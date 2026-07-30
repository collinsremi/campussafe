# CampusSafe

A shared food-safety board for campus life. Students report food poisoning,
hygiene issues, or unsafe storage at campus restaurants; admins review and
escalate; Gemma helps surface patterns and answer safety questions across
the live data.

Built for the Build with Gemma: AI for Africa Hackathon.

## Features

- Live safety board with per-restaurant scores and status (Safe / Watch / Alert)
- Student incident reporting (concern type, severity, details)
- Admin review queue — approve, escalate, or dismiss reports
- Campus-wide analytics: active reports, hotspots, response time, top concern patterns
- Gemma-powered assistant that answers safety questions using function calling —
  it decides whether to pull recent reports for a specific restaurant or
  the current campus-wide hotspots before answering
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
| `/api/assistant` | POST | Ask Gemma a safety question |
| `/api/config` | GET | Current model/config status |

## Roadmap

- Formal complaint drafting for direct handoff to Student Affairs / campus health
- Emergency-symptom guardrail for severe reports
- Photo evidence support (multimodal)
- Role-based access for admin actions
- Anonymous reporting option
