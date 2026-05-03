# 🧠 Master-MCP: The Autonomous Reasoning Engine

**Master-MCP** is a next-generation Model Context Protocol (MCP) server designed to transform standard AI agents into highly autonomous, self-correcting operational powerhouses. Built with a **Native-First** philosophy, it provides a blazingly fast, zero-dependency reasoning core that lives entirely on your hardware.

---

## ⚡ The Brain: Sequential Thinking & Orchestration
Unlike traditional MCP tools, Master-MCP features a sophisticated **Reasoning Loop** powered by `sequentialthinking`. This is the intelligence layer where the magic happens:

- **🤖 Autonomous Orchestration**: The engine analyzes the assistant's thoughts in real-time to predict the next best tool, calculate confidence scores, and identify the root cause of errors.
- **🧬 Hybrid Semantic Search**: Features a unified `search_semantic_memory` engine that synthesizes **Keyword Depth** (Ripgrep) with **Vector Intelligence** (Conceptual matching) for precise yet context-aware discovery.
- **🛡️ Intelligent Root Discovery**: Automatically identifies project boundaries by locating the `main.py` entry point or standard version control markers, ensuring zero-config orchestration.
- **🔄 Zero-Disk Loop Protection**: Advanced in-memory history tracking detects and breaks repetitive tool usage loops before they waste cycles.

---

## 🏗️ Modular Architecture
Master-MCP follows a **Micro-Modular Monolith** pattern for maximum maintainability and performance:

```text
mcp_master/
├── main.py            # Unified Entry Point & Root Marker
├── services/          # Pure Business Logic (Infrastructure, AI, Knowledge)
├── tools/             # AI Tool Interfaces (Thin Wrappers)
├── resources/         # Static Assets (bin, config, models, prompts)
└── internal/          # Development Workspace (scratch, scripts, tests)
```

---

## 🚀 Key Capabilities

### 🧠 Intelligence & Memory
- **Sequential Reasoning**: Dynamic linear and branching thought chains.
- **Hybrid Semantic Memory**: Multi-mode search (`code`, `memory`, `hybrid`) with transparent source tagging (`[K]` vs `[V]`).
- **Persistent Knowledge**: Durable fact storage with cross-session recall and deterministic root identification.

### 🔍 Codebase & File Operations
- **Deep Inspection**: Ultra-fast recursive search using bundled `ripgrep` integrated into the hybrid engine.
- **Smart Reading**: Native parsing for **PDF, DOCX, and EPUB** alongside source code.
- **Precision Refactoring**: Atomic multi-block replacements and syntax validation for Python, JS, TS, and more.

### 🌐 Research & Diagnostics
- **Live Discovery**: Real-time Web Search and StackOverflow integration.
- **System Awareness**: Deep hardware/OS diagnostics and network port checking.
- **Remote Execution**: Secure remote command orchestration (WSL/SSH).

---

## 📦 Native Performance (Pre-Bundled)
Master-MCP eliminates "Dependency Hell" by shipping with high-performance binaries pre-configured for Windows:
- **Ripgrep**: The gold standard for text search performance.
- **Ruff**: Lighting-fast Python linting and formatting.
- **Oxlint & Biome**: Modern, high-speed web development toolchain.
- **Embedded Llama**: Native multi-lingual embedding models.

---

## 🛠️ Quick Start

### 1. Installation
```bash
# Clone the core engine
git clone https://github.com/MSelcukAkbas/versatile-mcp.git
cd versatile-mcp

# Setup the environment
pip install -r requirements.txt
```

### 2. Configuration
Add Master-MCP to your MCP host settings (e.g., Claude Desktop). 

> [!TIP]
> **Zero-Config Root Discovery**: You no longer need manual markers! The engine automatically detects your project root by locating the `main.py` entry point or standard markers like `.git`.

```json
{
  "mcpServers": {
    "master-mcp": {
      "command": "python",
      "args": ["C:/absolute/path/to/mcp_master/main.py"],
      "env": {
        "STACK_EXCHANGE_API_KEY": "optional_key"
      }
    }
  }
}
```

---

## 🛡️ Privacy & Security
Master-MCP is built for **Private Reasoning**. Your thoughts, project code, and memory facts never leave your machine. The orchestration logic and semantic indexing are handled entirely offline by the embedded intelligence layer.

---
**Maintained by MSelcukAkbas** | [Project Origin](https://github.com/MSelcukAkbas/versatile-mcp)
