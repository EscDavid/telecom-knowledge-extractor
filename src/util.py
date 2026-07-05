"""Utilidades compartidas: hashing y lectura de texto de documentos."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

log = logging.getLogger("tkc.util")

TEXT_SUFFIXES = {".my", ".mib", ".txt", ".md"}
PDF_SUFFIXES = {".pdf"}


def sha256_file(path: Path) -> str:
    """SHA-256 del contenido binario — base del delta processing (fase futura)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def read_text(path: Path, max_pages: int | None = None) -> str:
    """Devuelve el texto del documento.

    - .my/.mib/.txt/.md → se leen directo.
    - .pdf → vía pdfplumber si está instalado; si no, string vacío con warning.
    `max_pages` limita la extracción (lo usa la capa header_text del Classifier).
    """
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix in PDF_SUFFIXES:
        return _read_pdf(path, max_pages)
    log.warning("Tipo de archivo no soportado para lectura de texto: %s", path.name)
    return ""


def _read_pdf(path: Path, max_pages: int | None) -> str:
    try:
        import pdfplumber  # import perezoso: solo se exige si hay PDFs
    except ImportError:
        log.warning("pdfplumber no instalado — no se puede leer %s. "
                    "Instala requirements.txt para procesar PDFs.", path.name)
        return ""
    parts: list[str] = []
    with pdfplumber.open(path) as pdf:
        pages = pdf.pages if max_pages is None else pdf.pages[:max_pages]
        for page in pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)
