import re
import sys
from pathlib import Path

# Single-anchor resolver — model-provided paths must be project-relative.
_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from core.path_utils import resolve, PathRejectedError, project_relative

TOOL_NAME        = "youtube_transcript"
TOOL_DESCRIPTION = ("Fetch the transcript of a YouTube video. Supports pagination via the 'block' argument "
                    "to traverse long transcripts.")
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "video":        {"type": "string", "description": "YouTube video URL or 11-char ID."},
    "language":     {"type": "string", "description": "ISO 639-1 language code preference."},
    "save_to":      {"type": "string", "description": "Project-relative path to save the full transcript."},
    "max_chars":    {"type": "integer", "description": "Cap the returned text (default 12000)."},
    "block":        {"type": "integer", "description": "Zero-indexed 15000-char block to return. Omit for first chunk."}
}

_ID_RE = re.compile(r"(?:v=|/(?:embed|shorts)/|youtu\.be/)([0-9A-Za-z_-]{11})")

def _extract_video_id(s: str) -> str:
    s = (s or "").strip()
    if not s: return ""
    if len(s) == 11 and re.fullmatch(r"[0-9A-Za-z_-]{11}", s): return s
    m = _ID_RE.search(s)
    return m.group(1) if m else ""

def execute(video: str, language: str = "en", save_to: str = "", max_chars: int = 12000, block: int = 0) -> str:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return "Error: youtube-transcript-api is not installed."

    video_id = _extract_video_id(video)
    if not video_id:
        return f"Error: invalid video id {video!r}"

    save_path = None
    if save_to:
        try:
            save_path = resolve(save_to)
        except PathRejectedError as e:
            return f"Error: {e}"

    try:
        api = YouTubeTranscriptApi()
        lang_pref = [language] if language else []
        if "en" not in lang_pref: lang_pref.append("en")
        fetched = api.fetch(video_id, languages=lang_pref)
        snippets = list(fetched)
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"

    if not snippets:
        return f"Error: No snippets for {video_id}"

    full_text = " ".join(getattr(s, "text", "").replace("\n", " ").strip() for s in snippets)
    full_text = re.sub(r"\s+", " ", full_text).strip()
    total_len = len(full_text)

    from core.identity import get_system_defaults
    BLOCK_SIZE = get_system_defaults().get("registry", {}).get("BLOCK_SIZE", 15000)
    start_idx = block * BLOCK_SIZE
    end_idx = start_idx + BLOCK_SIZE
    
    current_block_text = full_text[start_idx:end_idx]
    total_blocks = (total_len + BLOCK_SIZE - 1) // BLOCK_SIZE

    saved_msg = ""
    if save_path:
        try:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_text(full_text, encoding="utf-8")
            saved_msg = f"\nFull transcript saved to: {project_relative(save_path)}"
        except Exception as e:
            saved_msg = f"\nWarning: failed to save: {e}"

    display_text = current_block_text
    trunc_note = ""
    if max_chars and len(display_text) > max_chars:
        display_text = display_text[:max_chars]
        trunc_note = f"\n[truncated to {max_chars} chars]"

    footer = f"\n[BLOCK {block} OF {total_blocks - 1}]"
    if block < total_blocks - 1:
        footer += f" (Call again with block={block + 1} to continue)"

    return (f"Transcript for video {video_id} ({total_len} chars total, {len(snippets)} snippets):\n\n"
        f"{display_text}{trunc_note}{saved_msg}\n{footer}")