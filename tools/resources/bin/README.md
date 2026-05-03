# Master-MCP Resources: Binaries
This directory contains pre-compiled, local binaries used by the server's core tools (Search, Linting, Validation).

## Why Local Binaries?
To ensure a **"Batteries-Included"** experience and high performance without needing to install dozens of system-level dependencies. These tools are the "Swiss Army Knife" parts of our server.

## Platform Support

### 🪟 Windows (Pre-bundled)
The Windows binaries are located in `resources/bin/win32/x64/`. They are ready to use and automatically detected.

### 🐧 Linux
Linux binaries are **not** pre-bundled to keep the repository size manageable. Linux users should install these tools using their system's package manager:

- **ripgrep (rg)**: `sudo apt install ripgrep`
- **ruff**: `pip install ruff`
- **biome**: `npm install -g @biomejs/biome`

###  macOS
Similar to Linux, please use `brew`:
`brew install ripgrep ruff biome`

## Tools Included
- `rg`: Extremely fast text search (ripgrep).
- `ruff`: The fastest Python linter and formatter.
- `oxlint`: Advanced JavaScript/TypeScript linter.
- `biome`: Tooling for the web (JS/TS/JSON).

---
**Note for Windows Users:**
The binaries are already included. You can verify they are all present by running:
`python resources/bin/setup_bins.py`

**Note for Linux Users:**
Please refer to the "Linux" section above for manual installation instructions.
