"""Resolve response locale from UI setting and user message heuristics."""

from __future__ import annotations

import re

_SPANISH_HINTS = re.compile(
    r"\b("
    r"dame|listado|tablas|análisis|analisis|cuál|cual|qué|que|por favor|"
    r"necesito|muestra|muéstrame|muestrame|esquema|columnas|agrupar|"
    r"distintos|resumen|informe|datos|almacén|almacen|ingesta|cargar"
    r")\b",
    re.IGNORECASE,
)


def message_looks_spanish(message: str) -> bool:
    text = (message or "").strip()
    if not text:
        return False
    if _SPANISH_HINTS.search(text):
        return True
    # Accented Spanish chars without matching English-only UI default.
    return bool(re.search(r"[áéíóúñ¿¡]", text, re.IGNORECASE))


def resolve_response_locale(message: str, requested: str | None) -> str:
    """Return ``es`` or ``en`` — UI locale wins when ``es``; else infer from message."""
    req = (requested or "en").strip().lower()
    if req in ("es", "spanish", "es-ar", "es-es", "es-mx"):
        return "es"
    if message_looks_spanish(message):
        return "es"
    return "en"
