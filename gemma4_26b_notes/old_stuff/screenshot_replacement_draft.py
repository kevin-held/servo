import os
import base64
import json
from datetime import datetime
from pathlib import Path
from PIL import ImageGrab

TOOL_NAME        = "screenshot"
TOOL_DESCRIPTION = "Capture a screenshot and return the path and Base64 data for UI attachment."
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "output_path": {"type": "string", "description": "File path to save. Defaults to workspace/screenshots/"},
    "img_format":  {"type": "string", "description": "png or jpg."},
    "region":      {"type": "string", "description": "x1,y1,x2,y2."},
}

# Workspace sandbox root
_SANDBOX = Path(__file__).parent.parent.resolve()

def execute(output_path: str = "", img_format: str = "png", region: str = "") -> str:
    """
    Captures a screenshot and returns a JSON string containing the file path and Base64 encoded image.
    This allows the UI (ChatPanel) to automatically display the image in the attachment feature.
    """
    try:
        # 1. Normalize format
        img_format = img_format.lower().strip()
        if img_format not in ("png", "jpg", "jpeg"):
            img_format = "png"
        save_format = "JPEG" if img_format in ("jpg", "jpeg") else "PNG"
        ext = "jpg" if img_format in ("jpg", "jpeg") else "png"

        # 2. Resolve output path
        if not output_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = str(_SANDBOX / "screenshots" / f"screenshot_{timestamp}.{ext}")

        resolved = Path(output_path).resolve()

        # 3. Parse optional region
        bbox = None
        if region:
            try:
                coords = [int(x.strip()) for x in region.split(",")]
                if len(coords) == 4:
                    bbox = tuple(coords)
            except ValueError:
                return json.dumps({"status": "error", "message": "Invalid region format. Use 'x1,y1,x2,y2'."})

        # 4. Capture Screenshot
        screenshot = ImageGrab.grab(bbox=bbox)

        # 5. Ensure directory exists and save
        resolved.parent.mkdir(parents=True, exist_ok=True)
        screenshot.save(str(resolved), format=save_format)

        # 6. Encode to Base64 for the UI attachment feature
        with open(resolved, "rb") as img_file:
            b64_data = base64.b64encode(img_file.read()).decode('utf-8')

        # 7. Return JSON payload
        return json.dumps({
            "status": "success",
            "path": str(resolved),
            "format": save_format,
            "size": f"{screenshot.width}x{screenshot.height}",
            "b64": b64_data
        })

    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})
