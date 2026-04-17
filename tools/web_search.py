import urllib.request
import urllib.parse
import re

TOOL_NAME        = "web_search"
TOOL_DESCRIPTION = "Search the web to find URLs and brief snippets of information."
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "query": {"type": "string", "description": "The search query"},
    "max_results": {"type": "integer", "description": "Maximum number of results to return (default 5, max 10)"}
}

def execute(query: str, max_results: int = 5) -> str:
    max_results = min(max_results, 10)
    url = "https://lite.duckduckgo.com/lite/"
    data = urllib.parse.urlencode({'q': query}).encode('utf-8')
    req = urllib.request.Request(
        url, 
        data=data, 
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            html = response.read().decode('utf-8')
            
            # The HTML of lite.duckduckgo.com consists of results in tables.
            # We locate links using the result-snippet or a class tag
            
            # Extract main result links
            link_pattern = r'<a rel="nofollow" href="([^"]+)".*?>(.*?)</a>'
            raw_links = re.findall(link_pattern, html)
            
            results = []
            seen_urls = set()
            
            for link, title in raw_links:
                if link in seen_urls:
                    continue
                    
                # Clean up HTML tags in title
                clean_title = re.sub(r'<[^>]+>', '', title).strip()
                
                # Exclude DDG navigation links
                if not link.startswith('http'):
                    continue
                
                # Exclude Sponsored Ads
                if 'duckduckgo.com/y.js' in link:
                    continue
                    
                results.append(f"Title: {clean_title}\nURL: {link}")
                seen_urls.add(link)
                
                if len(results) >= max_results:
                    break
                    
            if not results:
                return "No results found for your query. Try a different search."
                
            output = f"Web Search Results for '{query}':\n\n"
            return output + "\n\n".join(results)
            
    except Exception as e:
        return f"Error executing web search: {str(e)}"
