from ddgs import DDGS
from services.core.logger_service import setup_logger
from typing import List, Dict

logger = setup_logger("SearchService")

class SearchService:
    """Service to handle web searches using DuckDuckGo."""
    
    def __init__(self):
        self.ddgs = DDGS()

    async def search(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        """Perform a text search on DuckDuckGo."""
        try:
            results = self.ddgs.text(query, max_results=max_results)
            return [
                {
                    "title": r.get('title', 'No Title'),
                    "href": r.get('href', 'No URL'),
                    "body": r.get('body', 'No Content')
                } for r in results
            ]
        except Exception as e:
            return [{"error": f"Search failed: {str(e)}"}]
