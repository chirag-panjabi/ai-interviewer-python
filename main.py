"""
main.py - Single-file FastAPI Application for AI Technical Interviewer
Monolithic architecture: REST API + Full-Duplex WebSockets (via Google GenAI SDK) + SQLite + Static UI.
"""
import os
import json
import base64
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from google import genai
from google.genai import types

from database import engine, Base, SessionLocal, Interview, Message, get_db
import github_service
import prompt_engine
import evaluator

# Initialize database schema
Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI Technical Interviewer (Python Monolith)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

# Mount static folder
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# HTML Page Serving Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=FileResponse)
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(index_file)


@app.get("/interview/{interview_id}", response_class=FileResponse)
async def serve_interview_page(interview_id: str):
    page = STATIC_DIR / "interview.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="interview.html not found")
    return FileResponse(page)


@app.get("/result/{interview_id}", response_class=FileResponse)
async def serve_result_page(interview_id: str):
    page = STATIC_DIR / "result.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="result.html not found")
    return FileResponse(page)


# ---------------------------------------------------------------------------
# REST Endpoints
# ---------------------------------------------------------------------------

class VerifyKeyRequest(BaseModel):
    apiKey: Optional[str] = None


@app.post("/api/verify-key")
async def verify_gemini_key(req: VerifyKeyRequest):
    key = (req.apiKey or "").strip() or os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        return {"valid": False, "message": "No API key provided or configured in .env."}

    # Verify key by listing models on Generative Language API
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return {"valid": True, "message": "Gemini API key is active and authorized."}
            else:
                return {"valid": False, "message": f"Google API returned HTTP {resp.status_code}: {resp.text}"}
    except Exception as e:
        return {"valid": False, "message": f"Connection check failed: {str(e)}"}


@app.get("/api/github-preview")
async def github_preview(username: str = Query(..., description="GitHub handle or URL")):
    token = os.getenv("GITHUB_TOKEN")
    profile = await github_service.fetch_github_profile(username, github_token=token)
    return profile


class PreInterviewRequest(BaseModel):
    username: str
    selectedRepo: Optional[str] = None
    apiKey: Optional[str] = None


@app.post("/api/pre-interview")
async def pre_interview(req: PreInterviewRequest, db: Session = Depends(get_db)):
    token = os.getenv("GITHUB_TOKEN")
    clean_username = github_service.parse_github_username(req.username)
    profile = await github_service.fetch_github_profile(clean_username, github_token=token)

    interview = Interview(
        status="CREATED",
        github_username=clean_username,
        selected_repo=req.selectedRepo,
    )
    interview.set_github_metadata(profile)
    db.add(interview)
    db.commit()
    db.refresh(interview)

    return {
        "interviewId": interview.id,
        "candidateName": profile.get("name") or clean_username,
        "selectedRepo": req.selectedRepo,
        "repoCount": len(profile.get("repos", [])),
    }


@app.get("/api/interview/{interview_id}")
async def get_interview_details(interview_id: str, db: Session = Depends(get_db)):
    interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    messages = (
        db.query(Message)
        .filter(Message.interview_id == interview_id)
        .order_by(Message.created_at.asc())
        .all()
    )

    return {
        "id": interview.id,
        "status": interview.status,
        "githubUsername": interview.github_username,
        "selectedRepo": interview.selected_repo,
        "metadata": interview.get_github_metadata(),
        "score": interview.score,
        "feedback": interview.feedback,
        "evaluation": interview.get_evaluation_data(),
        "messages": [{"id": m.id, "sender": m.sender, "text": m.text, "createdAt": m.created_at.isoformat()} for m in messages],
    }


class EndInterviewRequest(BaseModel):
    apiKey: Optional[str] = None


@app.post("/api/end-interview/{interview_id}")
async def end_interview(interview_id: str, req: Optional[EndInterviewRequest] = None, db: Session = Depends(get_db)):
    interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    interview.status = "COMPLETED"

    # Fetch messages
    messages = (
        db.query(Message)
        .filter(Message.interview_id == interview_id)
        .order_by(Message.created_at.asc())
        .all()
    )
    formatted_messages = [{"sender": m.sender, "text": m.text} for m in messages]

    # Resolve API Key
    api_key = (req.apiKey if req else None) or os.getenv("GEMINI_API_KEY", "").strip()

    # Trigger Evaluation Engine
    eval_result = await evaluator.evaluate_interview(
        messages=formatted_messages,
        github_metadata=interview.get_github_metadata(),
        api_key=api_key,
    )

    # Persist evaluation
    interview.score = int(round(eval_result.get("overallScore", 0) * 10))
    interview.feedback = eval_result.get("summary")
    interview.set_evaluation_data(eval_result)
    db.commit()

    return {"status": "COMPLETED", "evaluation": eval_result}


@app.get("/api/result-data/{interview_id}")
async def get_result_data(interview_id: str, db: Session = Depends(get_db)):
    interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    messages = (
        db.query(Message)
        .filter(Message.interview_id == interview_id)
        .order_by(Message.created_at.asc())
        .all()
    )

    eval_data = interview.get_evaluation_data()

    # If completed without evaluation, evaluate on-the-fly
    if not eval_data and interview.status == "COMPLETED":
        formatted_messages = [{"sender": m.sender, "text": m.text} for m in messages]
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        eval_data = await evaluator.evaluate_interview(
            messages=formatted_messages,
            github_metadata=interview.get_github_metadata(),
            api_key=api_key,
        )
        interview.score = int(round(eval_data.get("overallScore", 0) * 10))
        interview.feedback = eval_data.get("summary")
        interview.set_evaluation_data(eval_data)
        db.commit()

    return {
        "interviewId": interview.id,
        "status": interview.status,
        "candidate": {
            "username": interview.github_username,
            "selectedRepo": interview.selected_repo,
            "metadata": interview.get_github_metadata(),
        },
        "score": interview.score,
        "feedback": interview.feedback,
        "evaluation": eval_data,
        "transcript": [{"sender": m.sender, "text": m.text, "time": m.created_at.strftime("%H:%M:%S")} for m in messages],
    }


# ---------------------------------------------------------------------------
# Full-Duplex WebSockets Live Voice Stage (Google GenAI SDK)
# ---------------------------------------------------------------------------

@app.websocket("/api/live/{interview_id}")
async def live_voice_endpoint(websocket: WebSocket, interview_id: str, key: Optional[str] = Query(None)):
    await websocket.accept()

    db: Session = SessionLocal()
    interview = db.query(Interview).filter(Interview.id == interview_id).first()

    if not interview:
        await websocket.send_text(json.dumps({"type": "error", "message": "Interview not found"}))
        await websocket.close()
        db.close()
        return

    # Determine active API Key (Query param -> env)
    active_key = (key or "").strip() or os.getenv("GEMINI_API_KEY", "").strip()
    if not active_key:
        await websocket.send_text(json.dumps({"type": "error", "message": "No Gemini API key available."}))
        await websocket.close()
        db.close()
        return

    # Update interview status to IN_PROGRESS
    interview.status = "IN_PROGRESS"
    db.commit()

    # Compile system prompt
    metadata = interview.get_github_metadata() or {}
    selected_repo = interview.selected_repo
    system_prompt = prompt_engine.build_system_prompt(metadata, selected_repo)

    username = metadata.get("name") or interview.github_username or "Candidate"
    clean_name = username.split("-")[0].split("_")[0]

    opening_prompt_text = (
        f"Hello Alex! I am {clean_name}. I am ready for the technical screen. "
        f"Please introduce yourself briefly (1 sentence) and ask your first question based on my project '{selected_repo}'."
        if selected_repo
        else f"Hello Alex! I am {clean_name}. I am ready for the technical screen. Please introduce yourself and start."
    )

    model_name = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live")

    user_transcript_buffer = []
    assistant_transcript_buffer = []

    def flush_user_message():
        text = " ".join(user_transcript_buffer).strip()
        user_transcript_buffer.clear()
        if text:
            msg = Message(interview_id=interview_id, sender="User", text=text)
            db.add(msg)
            db.commit()

    def flush_assistant_message():
        text = "".join(assistant_transcript_buffer).strip()
        assistant_transcript_buffer.clear()
        if text:
            msg = Message(interview_id=interview_id, sender="Assistant", text=text)
            db.add(msg)
            db.commit()

    try:
        # Initialize Google GenAI SDK Client
        client = genai.Client(api_key=active_key, http_options={"api_version": "v1beta"})
        live_config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
                )
            ),
            system_instruction=types.Content(
                parts=[types.Part.from_text(text=system_prompt)]
            ),
        )

        print(f"[Live Session] Connecting to Google GenAI Live ({model_name}) for {interview_id}...")
        async with client.aio.live.connect(model=model_name, config=live_config) as session:
            # 1. Notify browser that connection is established
            await websocket.send_text(json.dumps({"type": "ready", "model": model_name}))

            # 2. Trigger initial turn so Alex greets candidate
            await session.send_client_content(
                turns=[
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=opening_prompt_text)],
                    )
                ],
                turn_complete=True,
            )

            async def client_to_gemini():
                """Forwards microphone PCM chunks and client events to Gemini Live."""
                try:
                    while True:
                        raw_data = await websocket.receive_text()
                        event = json.loads(raw_data)
                        event_type = event.get("type")

                        if event_type == "audio" and "pcm" in event:
                            raw_bytes = base64.b64decode(event["pcm"])
                            await session.send_realtime_input(
                                audio=types.Blob(mime_type="audio/pcm;rate=16000", data=raw_bytes)
                            )
                        elif event_type == "ping":
                            await websocket.send_text(json.dumps({"type": "pong"}))
                        elif event_type == "end":
                            break
                except WebSocketDisconnect:
                    pass
                except Exception as e:
                    print(f"[WebSocket Error client_to_gemini]: {e}")

            async def gemini_to_client():
                """Forwards Gemini audio, subtitles, and barge-in events to client."""
                try:
                    async for response in session.receive():
                        server_content = response.server_content
                        if server_content is not None:
                            # Model audio & text parts
                            model_turn = server_content.model_turn
                            if model_turn and model_turn.parts:
                                for part in model_turn.parts:
                                    if part.inline_data and part.inline_data.data:
                                        audio_b64 = base64.b64encode(part.inline_data.data).decode("utf-8")
                                        await websocket.send_text(json.dumps({
                                            "type": "audio",
                                            "pcm": audio_b64,
                                            "mimeType": "audio/pcm;rate=24000",
                                        }))
                                    if part.text:
                                        assistant_transcript_buffer.append(part.text)
                                        await websocket.send_text(json.dumps({
                                            "type": "transcript",
                                            "role": "assistant",
                                            "text": part.text,
                                        }))

                            # Live transcriptions
                            if getattr(server_content, "output_transcription", None):
                                text = server_content.output_transcription.text
                                if text:
                                    assistant_transcript_buffer.append(text)
                                    await websocket.send_text(json.dumps({
                                        "type": "transcript",
                                        "role": "assistant",
                                        "text": text,
                                    }))
                                    flush_user_message()

                            if getattr(server_content, "input_transcription", None):
                                text = server_content.input_transcription.text
                                if text:
                                    user_transcript_buffer.append(text)
                                    await websocket.send_text(json.dumps({
                                        "type": "transcript",
                                        "role": "user",
                                        "text": text,
                                    }))

                            # Barge-in Interruption
                            if getattr(server_content, "interrupted", False):
                                assistant_transcript_buffer.clear()
                                await websocket.send_text(json.dumps({"type": "interrupt"}))

                            # Turn Complete
                            if getattr(server_content, "turn_complete", False):
                                await websocket.send_text(json.dumps({"type": "turnComplete"}))
                                flush_assistant_message()

                except WebSocketDisconnect:
                    pass
                except Exception as e:
                    print(f"[WebSocket Error gemini_to_client]: {e}")

            # Run both streaming tasks concurrently
            await asyncio.gather(client_to_gemini(), gemini_to_client(), return_exceptions=True)

    except Exception as e:
        print(f"[WebSocket Session Fatal]: {e}")
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
        except Exception:
            pass
    finally:
        flush_user_message()
        flush_assistant_message()
        db.close()
        try:
            await websocket.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Direct Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    print(f"Starting AI Interviewer (Python Monolith) at http://localhost:{port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
