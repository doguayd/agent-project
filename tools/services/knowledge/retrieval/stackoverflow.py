import requests
import html
import re
from typing import List, Dict, Any, Optional
from services.core.logger_service import setup_logger

class StackOverflowService:
    """Service for searching and retrieving data from Stack Overflow via StackExchange API."""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.base_url = "https://api.stackexchange.com/2.3"
        self.logger = setup_logger("StackOverflowService")
        self.logger.info(f"Initialized with API Key: {'Available' if api_key else 'Missing (Throttled)'}")

    def _clean_html(self, raw_html: str) -> str:
        """Removes HTML tags and unescapes entities."""
        if not raw_html:
            return ""
        # Remove code blocks if needed? No, let's keep them but clean tags
        clean_re = re.compile('<.*?>')
        text = re.sub(clean_re, '', raw_html)
        return html.unescape(text)

    def search(self, query: str, max_results: int = 3) -> List[Dict[str, Any]]:
        """
        Searches Stack Overflow for technical answers.
        Prioritizes accepted answers and top-voted posts.
        """
        endpoint = f"{self.base_url}/search/advanced"
        params = {
            "q": query,
            "site": "stackoverflow",
            "accepted": "True",
            "order": "desc",
            "sort": "votes",
            "tags": "python",
            "filter": "withbody", # Returns body of the question
            "pagesize": max_results
        }
        
        if self.api_key:
            params["key"] = self.api_key

        try:
            self.logger.info(f"Searching for: {query}")
            response = requests.get(endpoint, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            results = []
            for item in data.get("items", []):
                question_id = item.get("question_id")
                accepted_answer_id = item.get("accepted_answer_id")
                
                result = {
                    "title": self._clean_html(item.get("title")),
                    "link": item.get("link"),
                    "question_body": self._clean_html(item.get("body"))[:1000] + "...",
                    "answer_body": "No accepted answer found in summary."
                }
                
                # If there's an accepted answer, try to fetch its body
                if accepted_answer_id:
                    answer_body = self._fetch_answer_body(accepted_answer_id)
                    if answer_body:
                        result["answer_body"] = answer_body
                
                results.append(result)
            
            return results

        except Exception as e:
            self.logger.error(f"Search failed: {str(e)}")
            return [{"error": f"StackOverflow search failed: {str(e)}"}]

    def _fetch_answer_body(self, answer_id: int) -> Optional[str]:
        """Fetches the body for a specific answer ID."""
        endpoint = f"{self.base_url}/answers/{answer_id}"
        params = {
            "site": "stackoverflow",
            "filter": "withbody"
        }
        if self.api_key:
            params["key"] = self.api_key
            
        try:
            response = requests.get(endpoint, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()
            items = data.get("items", [])
            if items:
                return self._clean_html(items[0].get("body"))
        except:
            pass
        return None
