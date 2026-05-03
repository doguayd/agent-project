# MasterMCP Araç Dokümantasyonu

Bu döküman, sunucuda kayıtlı tüm araçların teknik detaylarını ve LLM'e (asistan) sunulan tam açıklamalarını içerir.

> [!NOTE]
> Bu dosya otomatik olarak oluşturulmuştur. Güncellemek için `scripts/mcp_doc_sync.py` betiğini çalıştırın.

## Araç Listesi

### `apply_patch`
**Açıklama:** 
 Apply a unified diff patch to a file in-place.

---

### `ask_expert`
**Açıklama:** 
 Technical AI expert for code analysis and complex reasoning.

Args:
    prompt: The specific technical question or task description.
    context: Additional textual context (e.g. error logs, snippets).
    file_paths: List of file paths to include (supports 'path/to/file.py:10-50' range).
    background: If True, runs as a background task and returns a task_id.

---

### `create_plan`
**Açıklama:** 
 Analyze a problem and produce a structured execution plan before making changes.

USAGE INSTRUCTIONS FOR THE CALLING MODEL:
- Before calling this tool, reason through the problem thoroughly.
- YOU are responsible for producing the plan content — no external AI is used.
- Populate ALL fields based on your own analysis.

Parameters:
- goal: What the user ultimately wants to achieve.
- context: Relevant technical context (codebase, environment, constraints).
- constraints: Hard limitations or requirements (e.g. "do not modify auth logic").
- problem_analysis: {
    "core_problem": "Short explanation of the real underlying issue",
    "critical_points": ["risk", "edge case", "dependency impact"]
  }
- best_practices: Relevant engineering or architecture guidelines.
- risk_assessment: Possible breaking changes or performance impacts.
- execution_plan: [
    {"step": 1, "action": "...", "expected_result": "..."},
    ...
  ]

Returns: A task_id string you can use with task_mark_step to track progress.

---

### `diff_file_range_with_string`
**Açıklama:** 
 Bir dosyanın belirli bir satır aralığını sağlanan bir metin içeriğiyle karşılaştırır.

Args:
    target_file: Karşılaştırılacak dosyanın yolu.
    text: Dosya içeriğiyle karşılaştırılacak ham metin (string).
    start_line: Dosyanın okunmaya başlanacağı satır (1-indexed, opsiyonel).
    end_line: Dosyanın okunacağı son satır (dahil, opsiyonel).
    context_lines: Diff çıktısında gösterilecek bağlam satır sayısı (varsayılan: 3).

---

### `directory_tree`
**Açıklama:** 
 Returns a flattened 'Indexed File Graph' of the directory, optimized for AI reasoning.
Provides rich metadata (sizes, counts, types, roles) and respects .gitignore rules.

---

### `get_file_info`
**Açıklama:** 
 Get detailed metadata for a file.

---

### `http_request`
**Açıklama:** 
 Make an HTTP request to a local or private-network endpoint.
Only localhost and RFC-1918 private IPs are allowed.
method: GET | POST | PUT | DELETE | PATCH

---

### `manage_background_job`
**Açıklama:** 
 Unified tool for managing background OS processes and internal system tasks.

Actions:
- run: Start a new background terminal command. 'identifier' is the command string.
- status: Check status/output of a job. 'identifier' is the task_id.
- stop: Terminate a job. 'identifier' is the task_id.
- list: List all active background processes and system tasks.
- search: Find system processes by name. 'identifier' is the process name.

---

### `memory_index_workspace`
**Açıklama:** 
 Indexes the workspace for semantic search (Consolidated Service Call).

CRITICAL: This tool MUST be executed at the start of every project or session to enable semantic search and context retrieval.

---

### `memory_retrieve_facts`
**Açıklama:** 
 Retrieves stored project facts.

---

### `memory_store_fact`
**Açıklama:** 
 Stores a durable fact in project memory.

---

### `multi_replace_file_content`
**Açıklama:** 
 Apply multiple find-and-replace edits to a file in a single atomic operation.
Each chunk must contain 'target' (the exact text to find) and 'replacement' (the new text).
The operation is atomic: if any target chunk is not found, no changes are applied.

---

### `read_file`
**Açıklama:** 
 Smart unified file reader for text and rich documents (PDF, DOCX, EPUB).

Args:
    file_path: Path to the target file.
    mode: 'auto' (detect), 'text' (force text), or 'rich' (force doc extraction).
    start_line: Starting line number for text files (1-indexed).
    end_line: Ending line number for text files (inclusive).
    
Note: For PDF/DOCX, line parameters are ignored and 50k char limit applies.
Text files > 5MB require line ranges for safety.

---

### `read_multiple_files`
**Açıklama:** 
 Read multiple files at once.

---

### `remote_ssh_command`
**Açıklama:** 
 Executes a command on a remote server using sshpass through WSL.
This provides a way to connect to remote servers from Windows environments 
where sshpass is otherwise difficult to use.

Args:
    host: Remote server hostname or IP.
    user: SSH username.
    password: SSH password.
    command: The command to execute on the remote server.

---

### `search_files`
**Açıklama:** 
 Search for files matching a pattern.

---

### `search_semantic_memory`
**Açıklama:** 
 Advanced hybrid search across code and conceptual memory.

---

### `sequentialthinking`
**Açıklama:** 
 A detailed tool for dynamic reasoning and mini-agent planning.
This tool analyzes your thoughts, fetches auto-memory context, and suggests tools.
adapt and evolve. Each thought can build on, question, or revise previous insights.

When to use this tool:
- Breaking down complex problems into manageable steps.
- Planning and design with room for revision.
- Analysis that might need course correction.
- Problems where the full scope might not be clear initially.

Key features:
- Adjust total_thoughts up or down as you progress.
- Revise previous thoughts using is_revision + revises_thought.
- Branch into alternative approaches using branch_from_thought + branch_id.
- Add more thoughts even after reaching what seemed like the end.

Parameters:
- thought: Your current thinking step (analysis, hypothesis, etc.).
- thought_number: Current number in sequence.
- total_thoughts: Estimated remaining thoughts needed.
- next_thought_needed: True if more thinking is needed.
- context: Optional dict containing current context (e.g. status_code, service names).
- available_tools: Optional list of tool names (strings) you can use.
- memory_keys: Optional list of keywords to auto-retrieve past facts.

---

### `system_info`
**Açıklama:** 
 Return detailed system information about the machine running the MCP server.
Includes OS, platform, CPU, RAM, Python version, and working directory.
Use this to understand the execution environment before running platform-specific commands.

---

### `task_get_active`
**Açıklama:** 
 Retrieve all active, non-completed plans and their steps.

---

### `task_mark_step`
**Açıklama:** 
 Mark a specific step of a plan as 'todo', 'in_progress', or 'done'.
Call this after completing each step so progress is tracked.

---

### `validate_syntax`
**Açıklama:** 
 Validates code syntax using local high-performance engines (Ruff, Oxlint, Biome).

Supported Extensions:
- Python: .py
- JavaScript: .js, .mjs, .cjs
- TypeScript: .ts, .mts, .cts
- Data/Markup: .json, .yaml, .yml, .xml

Returns 'SUCCESS' if valid, or 'FAILURE: [Error Message]' on syntax error.

---

### `web_search`
**Açıklama:** 
 Hybrid Technical Research Tool. 
Simultaneously searches the general web and Stack Overflow for comprehensive answers.

---

### `workspace_summary`
**Açıklama:** 
 Comprehensive workspace analyzer tool. 
Extracts structure, technology, entrypoints, modules, and multi-factor hotspots.

CRITICAL: This tool MUST be executed at the start of every project or session to understand the architecture and project structure.

Args:
    project_root: Path to investigate (defaults to allowed root).
    mode: 'fast' (metadata only) or 'deep' (AST analysis, imports, health scores).
    max_depth: Maximum directory depth for scanning.
    
Use this tool when entering a new project or investigating technical debt/hotspots.

---

### `write_file`
**Açıklama:** 
 Write or overwrite a file.

---
