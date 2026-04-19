"""
youtube_transcript — fetch the transcript of a YouTube video.

Uses the youtube-transcript-api library. The library's surface changed
in its 1.x release (the Architect role's earlier draft in
workspace/gemma4_26b/youtube_transcript_extractor.py was calling the
removed YouTubeTranscriptApi.get_transcript() classmethod). The current
API is instance-based: YouTubeTranscriptApi().fetch(video_id) returns a
FetchedTranscript whose .snippets each have .text, .start, .duration.

Promoted from a workspace draft to a registered tool on 2026-04-18.
"""

import re
import sys
from pathlib import Path

# Single-anchor resolver — model-provided paths must be project-relative.
_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from core.path_utils import resolve, PathRejectedError, project_relative


TOOL_NAME        = "youtube_transcript"
TOOL_DESCRIPTION = ("Fetch the transcript of a YouTube video. Accepts a full URL "
                    "or a bare 11-character video ID. Returns the joined transcript "
                    "text. Optionally saves the full transcript to a project-relative "
                    "file path so the agent can re-read it later without re-fetching.")
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "video":        {"type": "string",
                     "description": "YouTube video URL (e.g. 'https://www.youtube.com/watch?v=dQw4w9WgXcQ') "
                                    "or bare 11-character video ID."},
    "language":     {"type": "string",
                     "description": "Optional ISO 639-1 language code preference (e.g. 'en', 'es'). "
                                    "Defaults to English then any auto-generated transcript."},
    "save_to":      {"type": "string",
                     "description": "Optional project-root-relative path to save the transcript "
                                    "(e.g. 'workspace/gemma4_26b/yt_transcript.txt'). Absolute paths "
                                    "are rejected. Leave empty to skip saving."},
    "max_chars":    {"type": "integer",
                     "description": "Cap the returned transcript text at this many characters "
                                    "(default: 12000, fits inside the standard 8k context budget). "
                                    "The full transcript is still saved to save_to if provided."},
}

# Matches the 11-char video ID inside common URL forms (youtube.com/watch?v=,
# youtu.be/, /embed/, /shorts/) — anchored on the typical separators.
_ID_RE = re.compile(r"(?:v=|/(?:embed|shorts)/|youtu\.be/)([0-9A-Za-z_-]{11})")


def _extract_video_id(s: str) -> str:
    """
    Pull an 11-char video id out of a URL, or accept the id directly.
    Returns the id string, or "" if neither matches.
    """
    s = (s or "").strip()
    if not s:
        return ""
    # Bare id
    if len(s) == 11 and re.fullmatch(r"[0-9A-Za-z_-]{11}", s):
        return s
    m = _ID_RE.search(s)
    return m.group(1) if m else ""


def execute(video: str, language: str = "en", save_to: str = "", max_chars: int = 12000) -> str:
    # Lazy import — the tool registry shouldn't crash on load if the library
    # is missing. The user can pip install on first use.
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return ("Error: youtube-transcript-api is not installed. "
                "Install with: pip install youtube-transcript-api")

    video_id = _extract_video_id(video)
    if not video_id:
        return (f"Error: could not extract a video id from {video!r}. "
                "Provide a full YouTube URL or a bare 11-character video id.")

    # Resolve save path early so a bad path fails before the network call.
    save_path = None
    if save_to:
        try:
            save_path = resolve(save_to)
        except PathRejectedError as e:
            return f"Error: {e}"

    try:
        api = YouTubeTranscriptApi()
        # Prefer the requested language, then English, then any auto-generated.
        # The library tries the languages list in order and falls back internally.
        lang_pref = [language] if language else []
        if "en" not in lang_pref:
            lang_pref.append("en")
        fetched = api.fetch(video_id, languages=lang_pref)
    except Exception as e:
        # Surface the library's error verbatim — it tends to be specific
        # (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable, etc.).
        return f"Error fetching transcript for video {video_id}: {type(e).__name__}: {e}"

    # FetchedTranscript is iterable; each snippet has .text/.start/.duration.
    try:
        snippets = list(fetched)
    except TypeError:
        # Some library versions expose .snippets explicitly.
        snippets = list(getattr(fetched, "snippets", []))

    if not snippets:
        return f"Error: transcript for {video_id} returned zero snippets."

    full_text = " ".join(getattr(s, "text", "").replace("\n", " ").strip() for s in snippets)
    full_text = re.sub(r"\s+", " ", full_text).strip()
    char_count = len(full_text)

    saved_msg = ""
    if save_path is not None:
        try:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_text(full_text, encoding="utf-8")
            saved_msg = f"\nFull transcript saved to: {project_relative(save_path)}"
        except Exception as e:
            saved_msg = f"\nWarning: failed to save transcript to {project_relative(save_path)}: {e}"

    truncated = ""
    if max_chars and char_count > max_chars:
        full_text = full_text[:max_chars]
        truncated = (f"\n[truncated to {max_chars} chars; full length was {char_count} chars"
                     f"{' — see saved file' if save_path is not None else ''}]")

    return (f"Transcript for video {video_id} ({char_count} chars, {len(snippets)} snippets):\n\n"
            f"{full_text}{truncated}{saved_msg}")
