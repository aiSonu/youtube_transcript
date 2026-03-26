"""
YouTube Transcript Server
-------------------------
Free, unlimited transcript fetching using youtube-transcript-api.
Deploy on Railway / Render / any Python host.

Install:
  pip install fastapi uvicorn youtube-transcript-api

Run locally:
  uvicorn main:app --host 0.0.0.0 --port 8000 --reload

Endpoints:
  GET  /transcript?videoId=xxx         - single video
  POST /transcripts/batch              - multiple videos at once
  GET  /health                         - health check
"""

from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)
from pydantic import BaseModel
from typing import Optional
import os
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="YouTube Transcript Server",
    description="Free transcript fetching for n8n YouTube Intelligence Agent",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple API key auth — set this as an env variable on your host
API_SECRET = os.environ.get("API_SECRET", "change-this-secret")


def verify_key(x_api_key: Optional[str] = Header(None)):
    if x_api_key != API_SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Api-Key header")


def fetch_transcript(video_id: str, lang: str = "en") -> dict:
    """
    Fetch transcript for a single video.
    Tries requested language first, then falls back to any available language.
    Returns dict with videoId, transcript (full text), source, and status.
    """
    try:
        # Try requested language first
        try:
            segments = YouTubeTranscriptApi.get_transcript(video_id, languages=[lang])
            full_text = " ".join(s["text"] for s in segments).replace("\n", " ").strip()
            return {
                "videoId": video_id,
                "transcript": full_text,
                "transcriptLength": len(full_text),
                "language": lang,
                "segmentCount": len(segments),
                "source": "youtube-transcript-api",
                "status": "success"
            }
        except NoTranscriptFound:
            # Fallback: try any available language
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            transcript = transcript_list.find_transcript(
                [t.language_code for t in transcript_list]
            )
            segments = transcript.fetch()
            full_text = " ".join(s["text"] for s in segments).replace("\n", " ").strip()
            return {
                "videoId": video_id,
                "transcript": full_text,
                "transcriptLength": len(full_text),
                "language": transcript.language_code,
                "segmentCount": len(segments),
                "source": "youtube-transcript-api (fallback lang)",
                "status": "success"
            }

    except TranscriptsDisabled:
        return {
            "videoId": video_id,
            "transcript": None,
            "status": "disabled",
            "reason": "Transcripts are disabled for this video"
        }
    except VideoUnavailable:
        return {
            "videoId": video_id,
            "transcript": None,
            "status": "unavailable",
            "reason": "Video is unavailable or private"
        }
    except Exception as e:
        logger.error(f"Error fetching transcript for {video_id}: {e}")
        return {
            "videoId": video_id,
            "transcript": None,
            "status": "error",
            "reason": str(e)
        }


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "YouTube Transcript Server"}


@app.get("/transcript")
def get_single_transcript(
    videoId: str,
    lang: str = "en",
    x_api_key: Optional[str] = Header(None)
):
    """
    Fetch transcript for a single video.
    Query params:
      videoId (required) — YouTube video ID e.g. dQw4w9WgXcQ
      lang    (optional) — language code, default 'en'
    """
    verify_key(x_api_key)

    if not videoId or len(videoId) < 5:
        raise HTTPException(status_code=400, detail="Invalid videoId")

    result = fetch_transcript(videoId, lang)
    return result


class BatchRequest(BaseModel):
    videoIds: list[str]
    lang: str = "en"
    delayMs: int = 300  # delay between requests to avoid IP rate limiting


@app.post("/transcripts/batch")
def get_batch_transcripts(
    body: BatchRequest,
    x_api_key: Optional[str] = Header(None)
):
    """
    Fetch transcripts for multiple videos in one call.
    Body:
      videoIds  — list of YouTube video IDs (max 20)
      lang      — language code, default 'en'
      delayMs   — ms delay between each fetch (default 300, min 100)
    """
    verify_key(x_api_key)

    if not body.videoIds:
        raise HTTPException(status_code=400, detail="videoIds list is empty")
    if len(body.videoIds) > 20:
        raise HTTPException(status_code=400, detail="Max 20 videos per batch request")

    delay = max(body.delayMs, 100) / 1000  # enforce min 100ms, convert to seconds
    results = []

    for i, video_id in enumerate(body.videoIds):
        logger.info(f"Fetching transcript {i+1}/{len(body.videoIds)}: {video_id}")
        result = fetch_transcript(video_id, body.lang)
        results.append(result)

        # Polite delay between requests — avoids YouTube IP rate limiting
        if i < len(body.videoIds) - 1:
            time.sleep(delay)

    successful = sum(1 for r in results if r["status"] == "success")
    failed     = len(results) - successful

    return {
        "total": len(results),
        "successful": successful,
        "failed": failed,
        "results": results
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
