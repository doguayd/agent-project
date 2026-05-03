from typing import Any, Optional, List
from fastmcp import FastMCP
from resources.config.settings import DEFAULT_MODEL

def register_ai_tools(mcp: FastMCP, ollama_svc, prompt_svc, diag_svc, file_svc, async_task_svc: Any = None):
    @mcp.tool()
    async def ask_expert(
        prompt: str,
        context: str = "",
        file_paths: Optional[List[str]] = None,
        background: bool = False
    ) -> str:
        """
        Technical AI expert for code analysis and complex reasoning.
        
        Args:
            prompt: The specific technical question or task description.
            context: Additional textual context (e.g. error logs, snippets).
            file_paths: List of file paths to include (supports 'path/to/file.py:10-50' range).
            background: If True, runs as a background task and returns a task_id.
        """
        err = await diag_svc.check_tool_dependency("ask_expert")
        if err:
            return err

        async def query_logic(task_id: Optional[str] = None):
            # Enrich context from files if provided
            final_context = context
            if file_paths:
                file_contents = []
                for item in file_paths:
                    path = item
                    start, end = None, None
                    if ":" in item:
                        try:
                            # Split from right to handle Windows paths like C:\path:10-20
                            path, range_part = item.rsplit(":", 1)
                            if "-" in range_part:
                                s, e = range_part.split("-")
                                start, end = int(s), int(e)
                        except: pass
                    
                    try:
                        content = file_svc.read_file(path, start, end)
                        range_str = f"Lines {start}-{end}" if start else "Full File"
                        file_contents.append(f"--- FILE: {path} ({range_str}) ---\n{content}")
                    except Exception as e:
                        file_contents.append(f"Error reading {path}: {str(e)}")
                
                final_context = "\n\n".join(file_contents) + ("\n\n" + context if context else "")

            # Dynamic prompt formatting via formatter.py
            try:
                from prompts.formatter import format_expert_prompt
                final_prompt = format_expert_prompt(prompt, final_context)
            except Exception as e:
                # Fallback to simple formatting if formatter fails or is missing
                final_prompt = f"# CONTEXT\n{final_context}\n\n---\n# QUESTION\n{prompt}"

            # Strictly use DEFAULT_MODEL from config
            return await ollama_svc.generate_response(DEFAULT_MODEL, final_prompt)

        if background and async_task_svc:
            task_name = f"Expert Analysis: {prompt[:30]}..."
            task_id = async_task_svc.run_task(query_logic, task_name)
            return f"AI Expert inquiry started in background.\n- Task ID: {task_id}\n- Model: {DEFAULT_MODEL}\n\nYou can continue working. Check the result later using 'get_background_task_status(task_id=\"{task_id}\")'."
        else:
            return await query_logic()
