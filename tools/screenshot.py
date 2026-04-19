import os
import sys
import base64
from datetime import datetime
from pathlib import Path

# Route every model-provided path through the single-anchor resolver.
_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from core.path_utils import resolve, PathRejectedError, project_relative

TOOL_NAME        = "screenshot"
TOOL_DESCRIPTION = "Capture a screenshot of the screen and save it to a file. Returns the saved file path so it can be attached or inspected."
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "output_path": {"type": "string",
                    "description": "Project-root-relative path where the screenshot should be saved. "
                                   "Example: 'workspace/gemma4_26b/screenshot.png'. "
                                   "Leave empty to auto-generate a timestamped path under workspace/screenshots/. "
                                   "Absolute paths and drive letters are rejected."},
    "img_format":  {"type": "string", "description": "Image format: 'png' (default) or 'jpg'."},
    "region":      {"type": "string", "description": "Optional screen region to capture as 'x1,y1,x2,y2' (e.g. '0,0,1920,1080'). Omit for full screen."},
}


def execute(output_path: str = "", img_format: str = "png", region: str = "") -> str:
    """
    Capture a screenshot and save it to the specified path within the workspace sandbox.

    Args:
        output_path: Where to save the screenshot. Defaults to workspace/screenshots/<timestamp>.png.
        img_format:  Image format (png or jpg). Default is 'png'.
        region:      Screen region as 'x1,y1,x2,y2'. Empty for full screen.

    Returns:
        String with the saved file path and image dimensions.
    """
    try:
        from PIL import ImageGrab
    except ImportError:
        return "Error: Pillow library not found. Install it with: pip install Pillow"

    try:
        # Normalize format
        img_format = img_format.lower().strip()
        if img_format not in ("png", "jpg", "jpeg"):
            img_format = "png"
        save_format = "JPEG" if img_format in ("jpg", "jpeg") else "PNG"
        ext = "jpg" if img_format in ("jpg", "jpeg") else "png"

        # Resolve output path — default to workspace/screenshots/ if blank.
        if not output_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"workspace/screenshots/screenshot_{timestamp}.{ext}"

        # Route through the single-anchor resolver. Rejection text is
        # surfaced to the model as the tool output — see decisions.md
        # D-20260417-09.
        try:
            resolved = resolve(output_path)
        except PathRejectedError as e:
            return f"Error: {e}"

        # Parse optional region
        bbox = None
        if region:
            try:
                coords = [int(x.strip()) for x in region.split(",")]
                if len(coords) == 4:
                    bbox = tuple(coords)
            except ValueError:
                return "Error: Invalid region format. Use 'x1,y1,x2,y2' with integer values."

        # Capture
        screenshot = ImageGrab.grab(bbox=bbox)

        # Ensure output directory exists
        resolved.parent.mkdir(parents=True, exist_ok=True)

        # Save
        screenshot.save(str(resolved), format=save_format)

        w, h = screenshot.size
        return (
            f"Screenshot captured successfully!\n"
            f"Saved to: {project_relative(resolved)}\n"
            f"Format: {save_format}\n"
            f"Size: {w}x{h} px"
        )

    except Exception as e:
        return f"Error capturing screenshot: {e}"
