import urllib.request
import re

TOOL_NAME        = "fetch_url"
TOOL_DESCRIPTION = "Read and extract text from a specific webpage URL."
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "url":        {"type": "string", "description": "The exact URL to read"},
    "block":      {"type": "integer", "description": "(Optional) Zero-indexed 15000-char block to return. Default 0."},
    "start_line": {"type": "integer", "description": "(Optional) 1-indexed start line to read."},
    "end_line":   {"type": "integer", "description": "(Optional) 1-indexed end line to read. Default is start_line + 500."},
}

def execute(url: str, block: int = 0, start_line: int = None, end_line: int = None) -> str:
    from core.identity import get_system_defaults
    _BLOCK_SIZE = get_system_defaults().get("registry", {}).get("BLOCK_SIZE", 15000)

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
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            total_lines = len(lines)
            text = '\n'.join(lines)
            total_len = len(text)
            
            body = text
            footer = ""

            # 0. Line-Range Logic (Precedence)
            if start_line is not None:
                start_line = max(1, int(start_line))
                if end_line is None:
                    end_line = start_line + 500
                else:
                    end_line = int(end_line)
                
                if start_line > total_lines:
                    return f"Error: start_line {start_line} exceeds total lines ({total_lines})."
                
                actual_end = min(end_line, total_lines)
                body = "\n".join(lines[start_line-1 : actual_end])
                footer = f"\n\n[Showing lines {start_line}-{actual_end} of {total_lines}]"
                if actual_end < total_lines:
                    footer += f"\nCall 'fetch_url' with start_line={actual_end+1} to continue."

            # 1. Block Pagination (Fallback)
            elif block > 0 or total_len > _BLOCK_SIZE:
                total_blocks = max(1, (total_len + _BLOCK_SIZE - 1) // _BLOCK_SIZE)
                if block < 0 or block >= total_blocks:
                    return f"Error: block {block} out of range (0..{total_blocks-1})."
                start = block * _BLOCK_SIZE
                end = min(start + _BLOCK_SIZE, total_len)
                body = text[start:end]
                footer = f"\n\n[BLOCK {block} OF {total_blocks-1} - chars {start}..{end-1} of {total_len}]"
                if block + 1 < total_blocks:
                    footer += f"\nCall 'fetch_url' with block={block+1} to continue."
            
            return body + footer
            
    except Exception as e:
        return f"Error fetching URL: {str(e)}"
