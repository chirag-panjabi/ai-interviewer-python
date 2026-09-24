# AI Technical Interviewer (Python Monolith Edition)

An autonomous, real-time AI technical interviewer built as a clean, single-command **Python FastAPI + SQLite monolith**. Conducts 12-minute live technical screens grounded in a candidate's actual GitHub repositories using full-duplex spoken audio with **Google Gemini 3.8 Live** and structured evaluations with **Gemini 3.5 Flash Lite**.

---

## 🌟 Architecture Overview

```
                      +---------------------------------------+
                      |           Modern Web Browser          |
                      |  - Web Audio DSP (48k -> 16k mono)    |
                      |  - Dual VoiceOrbs (Violet & Emerald)  |
                      |  - Live Subtitles (User & Alex STT)   |
                      |  - Instant Barge-in Buffer Flush      |
                      +---------------------------------------+
                                  ▲                │
                   24kHz PCM Audio│                │16kHz PCM Audio
                     & Subtitles  │                │(Real-Time Chunks)
                                  │                ▼
+---------------------------------------------------------------------------------+
|                       FastAPI Asynchronous Monolith Server                      |
|                                                                                 |
|  [REST API Endpoints]              [WebSocket Full-Duplex Proxy]                |
|  - POST /api/verify-key            - WS /api/live/{interview_id}                |
|  - GET  /api/github-preview        - asyncio.gather(client_to_gemini,           |
|  - POST /api/pre-interview                          gemini_to_client)           |
|  - POST /api/end-interview                                                      |
|  - GET  /api/result-data                                                        |
|                                                                                 |
|  [Domain Services]                                                              |
|  - github_service.py: Public repo inspection & cached profile grounding         |
|  - prompt_engine.py: Alex persona, XML repo containment, 2-sentence cadence     |
|  - evaluator.py: Structured 4-pillar scorecard via Gemini 3.5 Flash Lite        |
|                                                                                 |
|  [Persistence Layer]                                                            |
|  - SQLite (interview.db): Auto-created, zero config, transactional ACID logs    |
+---------------------------------------------------------------------------------+
                                  ▲                │
                     24kHz PCM/Tx │                │16kHz PCM Audio
                                  │                ▼
                      +---------------------------------------+
                      |    Google Gemini 3.8 Live WSS         |
                      | (BidiGenerateContent / Voice: Aoede)  |
                      +---------------------------------------+
```

---

## 🚀 Quickstart (Under 60 Seconds)

### 1. Prerequisites
- Python 3.10+ (Python 3.11, 3.12, or 3.13 recommended)
- A Google Gemini API Key from [Google AI Studio](https://aistudio.google.com/)

### 2. Setup Virtual Environment & Dependencies
```bash
cd ai-interviewer-python

# Using uv (fastest)
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt

# OR using standard python venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Environment Configuration
Create or edit `.env`:
```env
GEMINI_API_KEY="your-gemini-api-key-here"
GEMINI_LIVE_MODEL="gemini-3.8-live"
GEMINI_EVAL_MODEL="gemini-3.5-flash-lite"
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
├── evaluator.py        # Post-screen Gemini 3.5 Flash Lite 4-pillar evaluation engine
├── main.py             # FastAPI monolith: REST endpoints + WebSocket audio proxy
├── requirements.txt    # Python dependencies
├── .env                # Local secrets (API keys, ports)
├── .gitignore          # Ignores .env, .venv, database, and local docs
└── static/
    ├── index.html      # Candidate intake studio & repo selector
    ├── interview.html  # Live voice room with VoiceOrbs & real-time subtitles
    ├── result.html     # Hiring committee 4-pillar scorecard dossier
    └── js/
        ├── audio.js    # Web Audio DSP (linear resampler, jitter buffer, RMS meter)
        └── app.js      # REST API client & BYOK storage helper
```

---

## 🔑 Key Engineering Principles

1. **Monolithic Simplicity**: Zero Docker multi-container overhead, zero Redis broker dependencies. Everything runs inside a single, high-performance asynchronous Python process.
2. **Sub-400ms Spoken Latency**: The browser Web Audio API downsamples microphone input in real time from 48kHz to 16kHz Int16 PCM, streaming lightweight base64 chunks through an async WebSocket proxy directly to Gemini 3.8 Live.
3. **Live Subtitles (Two-Way STT)**: Initial handshake configures both `inputAudioTranscription: {}` and `outputAudioTranscription: {}`. The candidate sees their spoken words appear in real-time on screen as they speak, along with Alex's responses.
4. **Natural Barge-In Interruption**: When the candidate speaks while Alex is talking, Gemini triggers an `interrupted: true` frame. The browser immediately flushes active audio buffers, cutting Alex off in under 50ms without annoying speech overlap.
5. **Target Repository Grounding**: The candidate selects a flagship project from their public GitHub profile. Alex reads the README and architectural metadata to ask deep, relevant engineering questions.
6. **Prompt Injection Defense**: Untrusted README data is sanitized and placed inside strict `<untrusted_candidate_repo_context>` XML tags so malicious instructions in a candidate's repository cannot hijack Alex's persona or alter scores.
7. **4.5/10 Anti-Sycophancy Gate**: If the candidate scores below 4.5/10 on Technical Accuracy, the evaluation engine programmatically disallows "Hire" or "Strong Hire" recommendations, regardless of verbal confidence.
8. **Obsidian Aesthetic**: Styled in dark `#09090b` (zinc-950) with ambient radial glow, dynamic volume equalizers, and clean responsive glassmorphic cards.

---

## 📡 REST & WebSocket API Reference

| Endpoint | Method / Protocol | Description |
| :--- | :--- | :--- |
| `/` | `GET` | Serves the candidate intake and repository selection studio. |
| `/interview/{id}` | `GET` | Serves the live voice interview room. |
| `/result/{id}` | `GET` | Serves the final hiring committee scorecard. |
| `/api/verify-key` | `POST` | Validates a user-supplied Gemini API key. |
| `/api/github-preview` | `GET` | Fetches a candidate's GitHub profile and top public repositories. |
| `/api/pre-interview` | `POST` | Initializes an interview record in SQLite and stores candidate metadata. |
| `/api/live/{id}` | `WebSocket` | Full-duplex persistent audio bridge to Gemini 3.8 Live. |
| `/api/end-interview/{id}` | `POST` | Concludes interview and triggers Gemini 3.5 Flash Lite evaluation. |
| `/api/result-data/{id}` | `GET` | Retrieves full interview scorecard and turn-by-turn transcript. |

---

## 📄 License
MIT License. Open-source for developers and engineering teams.
