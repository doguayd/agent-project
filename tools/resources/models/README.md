# Local Models

This directory contains local model files (GGUF format) used by the Master MCP server for AI tasks such as embeddings, paraphrasing, and local inference.

## Models

- `paraphrase-multilingual-MiniLM-L12-118M-v2-Q8_0.gguf`: A quantized multilingual embedding model used for semantic search and memory indexing.

## Usage

Models in this directory are loaded by the `AIService` or specific specialized services. Ensure that GGUF files are placed here if they are intended to be used by the local provider.

> [!NOTE]
> This directory is typically excluded from Git via `.gitignore` to prevent large binary files from being tracked.
