import urllib.request
import re

TOOL_NAME        = "fetch_url"
TOOL_DESCRIPTION = "Read and extract text from a specific webpage URL."
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "url": {"type": "string", "description": "The exact URL to read"}
}

def execute(url: str) -> str:
    req = urllib.request.Request(
        url, 
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
            
            # Simple text extraction
            # 1. Remove script and style blocks
            html = re.sub(r'<(script|style).*?>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
            
            # 2. Convert common block tags to newlines
            html = re.sub(r'</?(p|div|br|h1|h2|h3|h4|h5|h6|li|tr)[^>]*>', '\n', html, flags=re.IGNORECASE)
            
            # 3. Strip remaining HTML tags
            text = re.sub(r'<[^>]+>', '', html)
            
            # 4. Clean up whitespace
            lines = [line.strip() for line in text.split('\n')]
            text = '\n'.join(line for line in lines if line)
            
            # Truncate if massive to prevent blowing up the local LLM context window
            if len(text) > 15000:
                text = text[:15000] + "\n...[TRUNCATED FOR LENGTH]..."
                
            return text
            
    except Exception as e:
        return f"Error fetching URL: {str(e)}"
