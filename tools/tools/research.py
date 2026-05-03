from typing import Optional, Dict, Any, List
import json
from fastmcp import FastMCP
from utils.decorators import mcp_timeout

def register_research_tools(mcp: FastMCP, search_svc, validator_svc, stackoverflow_svc, diag_svc, http_svc=None):  # noqa: E501
    @mcp.tool()
    @mcp_timeout(seconds=15)
    async def validate_syntax(content: Optional[str] = None, extension: Optional[str] = None, file_path: Optional[str] = None) -> str:
        """
        Validates code syntax using local high-performance engines (Ruff, Oxlint, Biome).
        
        Usage Modes:
        1. File Mode: Provide 'file_path'. Extension is auto-resolved.
        2. Content Mode: Provide 'content' and 'extension'.
        
        Supported Extensions:
        - Python: .py
        - JavaScript: .js, .mjs, .cjs
        - TypeScript: .ts, .mts, .cts
        - Data/Markup: .json, .yaml, .yml, .xml
        
        Returns 'SUCCESS' if valid, or 'FAILURE: [Error Message]' on syntax error.
        """
        err = await diag_svc.check_tool_dependency("validate_syntax")
        if err: return err

        if not file_path and not content:
            return "FAILURE: Either 'file_path' or 'content' must be provided."
        if content and not extension and not file_path:
            return "FAILURE: 'extension' is required when providing 'content' without a 'file_path'."

        valid, msg = validator_svc.validate(content, extension, file_path)
        return f"SUCCESS" if valid else f"FAILURE: {msg}"

    @mcp.tool()
    @mcp_timeout(seconds=20)
    async def web_search(query: str, max_results: int = 5) -> str:
        """
        Hybrid Technical Research Tool. 
        Simultaneously searches the general web and Stack Overflow for comprehensive answers.
        """
        import asyncio
        
        # Check dependencies first (informal)
        err_web = await diag_svc.check_tool_dependency("web_search")
        err_so = await diag_svc.check_tool_dependency("search_stackoverflow")
        
        if err_web and err_so:
            return f"Dependencies missing: {err_web}, {err_so}"

        # Parallel execution for speed
        tasks = [
            search_svc.search(query, max_results),
            stackoverflow_svc.search(query, max_results)
        ]
        
        web_results, so_results = await asyncio.gather(*tasks)
        
        output = []
        
        # 1. Format Stack Overflow (Technical Priority)
        if so_results and not isinstance(so_results, str):
            output.append("# 🔎 STACK OVERFLOW ÇÖZÜMLERİ\n")
            for r in so_results:
                if isinstance(r, dict) and "error" in r: continue
                # Ensure 'r' is a dictionary and has required keys
                title = r.get('title', 'No Title')
                link = r.get('link', '#')
                body = r.get('answer_body', 'No snippet available.')
                output.append(f"## {title}\nURL: {link}\n### Answer Snippet\n{body[:500]}...\n---\n")
        elif isinstance(so_results, str):
            output.append(f"StackOverflow Note: {so_results}")

        # 2. Format Web Results
        if web_results and not isinstance(web_results, str):
            output.append("\n# 🌐 WEB KAYNAKLARI (Dokümantasyon & Rehberler)\n")
            for r in web_results:
                title = r.get('title', 'No Title')
                href = r.get('href', '#')
                body = r.get('body', 'No content available.')
                output.append(f"### {title}\nURL: {href}\n{body}\n")
        elif isinstance(web_results, str):
            output.append(f"Web Note: {web_results}")

        if not output:
            return "Hiçbir sonuç bulunamadı."
            
        return "\n".join(output)

    @mcp.tool()
    async def http_request(
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        body: Optional[Any] = None,
        params: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> str:
        """
        Make an HTTP request to a local or private-network endpoint.
        Only localhost and RFC-1918 private IPs are allowed.
        method: GET | POST | PUT | DELETE | PATCH
        """
        if http_svc is None:
            return "HttpClientService is not available."
        result = await http_svc.request(method, url, headers=headers, body=body,
                                        params=params, timeout=timeout)
        if "error" in result:
            return f"Error: {result['error']}"
        latency = f"  ({result['latency_ms']} ms)" if result.get("latency_ms") else ""
        return (
            f"Status: {result['status_code']}{latency}\n"
            f"Headers: {json.dumps(dict(result['headers']), indent=2)}\n"
            f"Body:\n{result['body']}"
        )
