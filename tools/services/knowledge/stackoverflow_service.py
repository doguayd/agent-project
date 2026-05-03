import httpx
import json
import logging
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
from services.core.logger_service import setup_logger

logger = setup_logger("StackOverflowService")

class StackOverflowService:
    """Service to interact with Stack Exchange API."""
    
    BASE_URL = "https://api.stackexchange.com/2.3"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.site = "stackoverflow"

    def _html_to_markdown(self, html: str) -> str:
        """
        Convert HTML content to simple Markdown.
        Wrapped in try-catch to ensure robustness.
        """
        try:
            if not html:
                return ""
            
            soup = BeautifulSoup(html, 'html.parser')
            
            # Simple conversions
            for code in soup.find_all('code'):
                code.replace_with(f"`{code.get_text()}`")
            
            for pre in soup.find_all('pre'):
                lang = "" # Could detect language if needed
                pre.replace_with(f"\n```\n{pre.get_text()}\n```\n")
                
            for b_tag in soup.find_all(['b', 'strong']):
                b_tag.replace_with(f"**{b_tag.get_text()}**")
                
            for i_tag in soup.find_all(['i', 'em']):
                i_tag.replace_with(f"*{i_tag.get_text()}*")

            for a_tag in soup.find_all('a'):
                href = a_tag.get('href', '')
                a_tag.replace_with(f"[{a_tag.get_text()}]({href})")

            # Get text and clean up extra whitespace
            text = soup.get_text()
            lines = [line.strip() for line in text.split('\n')]
            return '\n'.join([line for line in lines if line])
            
        except Exception as e:
            logger.warning(f"HTML conversion error: {str(e)}")
            # Fallback: just return the HTML or a message
            return f"--- Error converting HTML ---\n{html}"

    async def search(self, query: str, max_results: int = 3) -> List[Dict]:
        """
        Search for questions and their accepted answers.
        """
        results = []
        api_key_status = "with key" if self.api_key else "no key (300 req/day limit)"
        logger.info(f"SO search | query='{query[:80]}' | max={max_results} | {api_key_status}")

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # 1. Search for questions
                search_params = {
                    "order": "desc",
                    "sort": "relevance",
                    "q": query,
                    "site": self.site,
                    "accepted": "True",
                    "filter": "withbody"
                }
                if self.api_key:
                    search_params["key"] = self.api_key

                logger.debug(f"SO search | GET /search/advanced | params={list(search_params.keys())}")
                response = await client.get(f"{self.BASE_URL}/search/advanced", params=search_params)
                response.raise_for_status()
                data = response.json()
                
                items = data.get("items", [])[:max_results]
                logger.info(f"SO search | {len(items)} question(s) found (quota_remaining={data.get('quota_remaining', '?')})")
                
                for idx, item in enumerate(items):
                    question_id = item.get("question_id")
                    title = item.get("title")
                    link = item.get("link")
                    q_body_html = item.get("body")
                    ans_id = item.get("accepted_answer_id")
                    
                    logger.debug(f"SO search | [{idx+1}] qid={question_id} | ans_id={ans_id} | '{title[:60]}'")

                    res_item = {
                        "title": title,
                        "link": link,
                        "question_body": self._html_to_markdown(q_body_html),
                        "answer_body": "No answer found."
                    }
                    
                    if ans_id:
                        ans_params = {"site": self.site, "filter": "withbody"}
                        if self.api_key:
                            ans_params["key"] = self.api_key
                            
                        ans_res = await client.get(f"{self.BASE_URL}/answers/{ans_id}", params=ans_params)
                        logger.debug(f"SO search | answer fetch | ans_id={ans_id} | status={ans_res.status_code}")

                        if ans_res.status_code == 200:
                            ans_data = ans_res.json()
                            if ans_data.get("items"):
                                ans_body_html = ans_data["items"][0].get("body")
                                res_item["answer_body"] = self._html_to_markdown(ans_body_html)
                                logger.debug(f"SO search | answer fetched | ans_id={ans_id} | body_len={len(ans_body_html or '')}")
                    
                    results.append(res_item)

                logger.info(f"SO search | complete | {len(results)} result(s) returned")
                    
        except Exception as e:
            logger.error(f"SO search | FAILED | query='{query[:80]}' | error={str(e)}")
            results.append({"error": str(e)})
            
        return results

