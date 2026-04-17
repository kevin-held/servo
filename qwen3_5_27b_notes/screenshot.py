import os
import base64
from datetime import datetime
from PIL import ImageGrab

TOOL_NAME        = "screenshot"
TOOL_DESCRIPTION = "Capture a screenshot of the screen and save it to a specified output path."
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "output_path": {"type": "string", "description": "The file path where the screenshot should be saved (e.g., 'C:/screenshots/capture.png'). If not provided, defaults to qwen3_5_27b_notes with timestamp."},
    "format": {"type": "string", "description": "Image format for saving (png, jpg, jpeg). Default is 'png'."},
    "region": {"type": "string", "description": "Optional screen region to capture as 'x1,y1,x2,y2' (e.g., '0,0,1920,1080'). If not provided, captures full screen."}
}

def execute(output_path: str = None, format: str = "png", region: str = None) -> str:
    """
    Capture a screenshot and save it to the specified path.
    
    Args:
        output_path: Where to save the screenshot. Defaults to workspace notes folder with timestamp.
        format: Image format (png, jpg, jpeg). Default is 'png'.
        region: Screen region as 'x1,y1,x2,y2'. None for full screen.
    
    Returns:
        A string containing the saved file path and optional base64 encoded image data.
    """
    try:
        # Set default output path if not provided
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_dir = "C:/Users/kevin/OneDrive/Desktop/ai/qwen3_5_27b_notes"
            os.makedirs(default_dir, exist_ok=True)
            output_path = os.path.join(default_dir, f"screenshot_{timestamp}.{format}")
        
        # Parse region if provided
        bbox = None
        if region:
            coords = [int(x) for x in region.split(",")]
            if len(coords) == 4:
                bbox = tuple(coords)
        
        # Capture screenshot
        if bbox:
            screenshot = ImageGrab.grab(bbox=bbox)
        else:
            screenshot = ImageGrab.grab()
        
        # Normalize format
        format = format.lower()
        if format == "jpeg":
            format = "jpg"
        
        # Ensure directory exists
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        
        # Save screenshot
        screenshot.save(output_path, format=format.upper())
        
        # Generate base64 encoded image (following chat_panel.py pattern)
        from io import BytesIO
        buffer = BytesIO()
        screenshot.save(buffer, format=format.upper())
        img_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        # Return result
        result = f"Screenshot captured successfully!\n"
        result += f"Saved to: {output_path}\n"
        result += f"Format: {format.upper()}\n"
        result += f"Size: {screenshot.size[0]}x{screenshot.size[1]}\n"
        result += f"\nBase64 encoded image data available (length: {len(img_b64)} chars)"
        
        # Store base64 data in a separate file for retrieval if needed
        b64_path = output_path + ".b64"
        with open(b64_path, "w") as f:
            f.write(img_b64)
        result += f"\nBase64 data saved to: {b64_path}"
        
        return result
        
    except ImportError:
        return "Error: PIL/Pillow library not found. Please install it with: pip install Pillow"
    except Exception as e:
        return f"Error capturing screenshot: {str(e)}"
