import os
import base64
from datetime import datetime
from pathlib import Path

TOOL_NAME        = "screenshot"
TOOL_DESCRIPTION = "Capture a screenshot of the screen and save it to a file. Returns the saved file path so it can be attached or inspected."
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "output_path": {"type": "string", "description": "File path where the screenshot should be saved. Defaults to a timestamped file in the workspace screenshots/ folder. Always use forward slashes."},
    "img_format":  {"type": "string", "description": "Image format: 'png' (default) or 'jpg'."},
    "region":      {"type": "string", "description": "Optional screen region to capture as 'x1,y1,x2,y2' (e.g. '0,0,1920,1080'). Omit for full screen."},
}

# Workspace sandbox root — mirrors boundary in filesystem.py
_SANDBOX = Path(__file__).parent.parent.resolve()


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

        # Resolve output path — default to workspace/screenshots/
        if not output_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = str(_SANDBOX / "screenshots" / f"screenshot_{timestamp}.{ext}")

        resolved = Path(output_path).resolve()

        # Sandbox enforcement
        if not str(resolved).lower().startswith(str(_SANDBOX).lower()):
            return f"Error: Access denied. '{output_path}' is outside the allowed workspace sandbox."

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
            f"Saved to: {resolved}\n"
            f"Format: {save_format}\n"
            f"Size: {w}x{h} px"
        )

    except Exception as e:
        return f"Error capturing screenshot: {e}"
