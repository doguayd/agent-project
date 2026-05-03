import os
import fitz  # PyMuPDF
import docx
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional
from services.core.logger_service import setup_logger

logger = setup_logger("DocumentService")

class DocumentService:
    """Service to handle text extraction from various document formats."""

    def __init__(self):
        logger.info("DocumentService initialized.")

    def extract_text(self, file_path: str) -> str:
        """Dispatcher function for different file extensions."""
        ext = os.path.splitext(file_path)[1].lower()
        
        try:
            if ext == ".pdf":
                return self._extract_pdf(file_path)
            elif ext == ".docx":
                return self._extract_docx(file_path)
            elif ext in [".epub", ".mobi"]:
                return self._extract_epub(file_path)
            else:
                logger.warning(f"Unsupported format for extraction: {ext}")
                return ""
        except Exception as e:
            logger.error(f"Failed to extract text from {file_path}: {e}")
            return ""

    def _extract_pdf(self, path: str) -> str:
        """Extract text from PDF using PyMuPDF."""
        text = ""
        with fitz.open(path) as doc:
            for page in doc:
                text += page.get_text() + "\n"
        return text

    def _extract_docx(self, path: str) -> str:
        """Extract text from Word .docx files."""
        doc = docx.Document(path)
        return "\n".join([para.text for para in doc.paragraphs])

    def _extract_epub(self, path: str) -> str:
        """Extract text from EPUB using ebooklib and BeautifulSoup."""
        book = epub.read_epub(path)
        chapters = []
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                soup = BeautifulSoup(item.get_content(), 'html.parser')
                chapters.append(soup.get_text())
        return "\n".join(chapters)

    def chunk_text(self, text: str, chunk_size_lines: int = 50, overlap_lines: int = 10) -> List[Dict[str, Any]]:
        """Split large text into line-aware chunks with overlap for better RAG indexing."""
        if not text:
            return []
            
        lines = text.splitlines()
        chunks = []
        start = 0
        
        while start < len(lines):
            end = min(start + chunk_size_lines, len(lines))
            chunk_content = "\n".join(lines[start:end])
            
            chunks.append({
                "content": chunk_content,
                "line_start": start + 1,
                "line_end": end,
                "total_lines": len(lines)
            })
            
            if end == len(lines):
                break
            start += (chunk_size_lines - overlap_lines)
            
        return chunks
