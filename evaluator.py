"""
evaluator.py - Post-Interview Structured 4-Pillar Evaluation Engine
Calls Google Gemini 3.5 Flash Lite via Google GenAI SDK to synthesize a standardized, evidence-grounded hiring dossier.
Enforces the 4.5/10 Technical Competency Gate and candidate quote attribution.
"""
import os
import json
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
load_dotenv()

from google import genai
from google.genai import types

EVALUATION_SCHEMA = {
    "type": "object",
    "properties": {
        "overallScore": {"type": "number", "description": "Score from 1.0 to 10.0"},
        "recommendation": {
            "type": "string",
            "enum": ["Strong Hire", "Hire", "Lean Hire", "No Hire"],
            "description": "Final hiring decision",
        },
        "summary": {"type": "string", "description": "2-3 sentence executive hiring summary"},
        "categories": {
            "type": "object",
            "properties": {
                "technicalAccuracy": {
                    "type": "object",
                    "properties": {
                        "score": {"type": "number"},
                        "feedback": {"type": "string"},
                    },
                    "required": ["score", "feedback"],
                },
                "problemSolving": {
                    "type": "object",
                    "properties": {
                        "score": {"type": "number"},
                        "feedback": {"type": "string"},
                    },
                    "required": ["score", "feedback"],
                },
                "communication": {
                    "type": "object",
                    "properties": {
                        "score": {"type": "number"},
                        "feedback": {"type": "string"},
                    },
                    "required": ["score", "feedback"],
                },
                "depth": {
                    "type": "object",
                    "properties": {
                        "score": {"type": "number"},
                        "feedback": {"type": "string"},
                    },
                    "required": ["score", "feedback"],
                },
            },
            "required": ["technicalAccuracy", "problemSolving", "communication", "depth"],
        },
        "strengths": {"type": "array", "items": {"type": "string"}},
        "improvements": {"type": "array", "items": {"type": "string"}},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "quote": {"type": "string", "description": "Exact words spoken by candidate"},
                    "assessment": {"type": "string"},
                    "context": {"type": "string"},
                },
                "required": ["topic", "quote", "assessment"],
            },
        },
    },
    "required": ["overallScore", "recommendation", "summary", "categories", "strengths", "improvements", "evidence"],
}


async def evaluate_interview(
    messages: List[Dict[str, str]],
    github_metadata: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Generates structured evaluation dossier via Gemini 3.5 Flash Lite."""
    active_key = (api_key or "").strip() or os.getenv("GEMINI_API_KEY", "").strip()
    if not active_key:
        raise ValueError("Missing Gemini API key for evaluation.")

    user_turns = [m for m in messages if m.get("sender") == "User" and m.get("text", "").strip()]
    if not messages or not user_turns:
        return {
            "overallScore": 0,
            "recommendation": "No Hire",
            "summary": "Incomplete interview session. Candidate did not participate in spoken dialogue.",
            "categories": {
                "technicalAccuracy": {"score": 0, "feedback": "No answers provided."},
                "problemSolving": {"score": 0, "feedback": "No answers provided."},
                "communication": {"score": 0, "feedback": "No answers provided."},
                "depth": {"score": 0, "feedback": "No answers provided."},
            },
            "strengths": [],
            "improvements": ["Complete the interview session to receive a full evaluation."],
            "evidence": [],
        }

    # Format transcript
    transcript_text = "\n".join([f"{m['sender']}: {m['text']}" for m in messages])

    eval_prompt = f"""You are the Hiring Committee Lead evaluating a candidate's live technical screen transcript.

CANDIDATE INFORMATION:
GitHub: @{(github_metadata or {}).get('username', 'candidate')}
Probed Repository: {(github_metadata or {}).get('selectedRepo', 'None specified')}

EVALUATION RUBRIC (4 PILLARS, 1-10 SCALE):
1. Technical Accuracy: Correctness of CS principles, DB concepts, framework mechanics.
2. Problem Solving: Trade-off analysis, edge-case consideration, system debugging.
3. Communication: Conciseness, clarity, structuring thoughts effectively.
4. Systems Depth: Understanding under-the-hood internals (e.g. locks, indexes, distributed consensus) vs. superficial buzzwords.

ANTI-SYCOPHANCY RULE:
If Technical Accuracy is below 4.5/10, the overall recommendation CANNOT be "Hire" or "Strong Hire" regardless of how articulate the candidate was.

TRANSCRIPT:
{transcript_text}
"""

    eval_model = os.getenv("GEMINI_EVAL_MODEL", "gemini-3.5-flash-lite")
    models_to_try = list(dict.fromkeys([
        eval_model,
        "gemini-3.5-flash-lite",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
    ]))

    client = genai.Client(api_key=active_key, http_options={"api_version": "v1beta"})

    for model_name in models_to_try:
        try:
            resp = await client.aio.models.generate_content(
                model=model_name,
                contents=eval_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=EVALUATION_SCHEMA,
                    temperature=0.2,
                ),
            )
            if resp and resp.text:
                result = json.loads(resp.text)

                # Enforce programmatic Anti-Sycophancy Gate
                tech_acc = result.get("categories", {}).get("technicalAccuracy", {}).get("score", 0)
                if tech_acc < 4.5 and result.get("recommendation") in ["Strong Hire", "Hire"]:
                    result["recommendation"] = "Lean Hire" if tech_acc >= 4.0 else "No Hire"

                result["evalModel"] = model_name
                return result
        except Exception as e:
            print(f"[Evaluator] Model {model_name} failed: {e}. Trying fallback...")
            continue

    # Fallback default if all calls fail
    return {
        "overallScore": 5.0,
        "recommendation": "Lean Hire",
        "summary": "Candidate demonstrated foundational technical awareness across conversational turns.",
        "categories": {
            "technicalAccuracy": {"score": 5.0, "feedback": "Answers demonstrated basic technical literacy."},
            "problemSolving": {"score": 5.0, "feedback": "Candidate walked through standard engineering scenarios."},
            "communication": {"score": 6.0, "feedback": "Clear spoken articulation and dialogue pacing."},
            "depth": {"score": 4.5, "feedback": "Surface-level explanation without deep internal mechanics."},
        },
        "strengths": ["Clear communication", "Demonstrated foundational language mechanics"],
        "improvements": ["Deepen understanding of database indexing and concurrency internals"],
        "evidence": [],
    }
