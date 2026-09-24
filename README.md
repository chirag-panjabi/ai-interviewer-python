# AI Technical Interviewer (Python Monolith Edition)

An autonomous, real-time AI technical interviewer built as a clean, single-command **Python FastAPI + SQLite monolith**. Conducts 12-minute live technical screens grounded in a candidate's actual GitHub repositories using full-duplex spoken audio with **Google Gemini 2.0 Flash Live**.

---

## 🌟 Architecture Overview

```
                      +---------------------------------------+
                      |           Modern Web Browser          |
                      |  - Web Audio DSP (48k -> 16k mono)    |
                      |  - Dual VoiceOrbs (RMS audio sync)    |
                      |  - Live Subtitles & Barge-in Stop     |
                      +---------------------------------------+
                                  ▲                │
                   24kHz PCM Audio│                │16kHz PCM Audio
                     & Subtitles  │                │(Realtime Chunks)
                                  │                ▼
+---------------------------------------------------------------------------------+
|                       FastAPI Asynchronous Monolith Server                      |
|                                                                                 |
|  [REST API Endpoints]              [WebSocket Audio Hub]                        |
|  - POST /api/verify-key            - WS /api/live/{interview_id}                |
|  - GET  /api/github-preview        - asyncio.gather(client_to_gemini,           |
|  - POST /api/pre-interview                          gemini_to_client)           |
|  - POST /api/end-interview                                                      |
|  - GET  /api/result-data                                                        |
|                                                                                 |
|  [Domain Services]                                                              |
|  - github_service.py: Public repo inspection & cached profile grounding         |
|  - prompt_engine.py: Alex persona, XML sandbox, 2-sentence conversational turn  |
|  - evaluator.py: Post-screen Gemini Flash synthesis with 4.5/10 anti-sycophancy |
|                                                                                 |
|  [Persistence Layer]                                                            |
|  - SQLite (interview.db): Auto-created, zero config, transactional ACID logs    |
+---------------------------------------------------------------------------------+
                                  ▲                │
                     24kHz PCM/Tx │                │16kHz PCM Audio
                                  │                ▼
                      +---------------------------------------+
                      |       Google Gemini Live WSS          |
                      |   (BidiGenerateContent / Aoede)      |
                      +---------------------------------------+
```

---

## 🚀 Quickstart (Under 60 Seconds)

### 1. Prerequisites
- Python 3.10+ (Python 3.11, 3.12, or 3.13 recommended)
- A Google Gemini API Key

### 2. Setup Virtual Environment & Dependencies
```bash
cd ai-interviewer-python

# Using uv (instant)
uv venv
source .venv/bin/activate
uv pip install fastapi uvicorn[standard] websockets httpx python-dotenv pydantic sqlalchemy

# OR using standard python venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Environment Configuration
Create or edit `.env`:
```env
GEMINI_API_KEY="your-gemini-api-key-here"
GEMINI_LIVE_MODEL="gemini-2.0-flash-exp"
PORT=8000
```

### 4. Launch the Server
```bash
uvicorn main:app --reload --port 8000
```

Open your browser to:
👉 **`http://localhost:8000`**

---

## 📁 Repository Structure

```
ai-interviewer-python/
├── database.py         # SQLAlchemy SQLite models (Interview, Message)
├── github_service.py   # GitHub profile & repository extraction with TTL caching
├── prompt_engine.py    # Alex persona, XML repo containment, 2-sentence turns
├── evaluator.py        # Post-screen Gemini Flash 4-pillar evaluation engine
├── main.py             # FastAPI monolith: REST endpoints + WebSocket audio proxy
├── interview.db        # Auto-created SQLite database file
├── .env                # Local secrets (Gemini API Key, Port)
├── requirements.txt    # Python dependencies
├── STUDY_GUIDE.md      # 10-minute interview cheat sheet & design defense
└── static/
    ├── index.html      # Candidate intake studio & repo selector
    ├── interview.html  # Live voice room with VoiceOrbs & real-time subtitles
    ├── result.html     # Hiring committee 4-pillar scorecard dossier
    └── js/
        ├── audio.js    # Web Audio DSP (linear resampler, jitter buffer, RMS)
        └── app.js      # REST API client & BYOK storage
```

---

## 🔑 Key Engineering Principles

1. **Monolithic Simplicity**: Zero multi-container Docker compose or Redis queues required. Everything runs in a single Python runtime.
2. **Sub-400ms Spoken Latency**: Browser Web Audio downsamples mic input from 48kHz to 16kHz Int16 PCM, streaming lightweight base64 chunks through an async WebSocket proxy directly to Gemini Live.
3. **Barge-In Interruption**: When candidate speaks over Alex, Gemini triggers `interrupted: true`, immediately draining the browser's active audio buffers with zero overlap.
4. **Target Project Grounding**: Candidate selects a specific repository from their GitHub. The prompt engine anchors all high-level architecture and mechanics questions to that codebase.
5. **Anti-Sycophancy Gate**: If the candidate scores below 4.5/10 on Technical Accuracy, the evaluation engine programmatically disallows "Hire" or "Strong Hire" regardless of verbal eloquence.
