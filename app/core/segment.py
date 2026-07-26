"""
Normalização de segmento de cliente — usada tanto no consumidor (insights.py,
Story 27.1) quanto no produtor (pipeline.py, Story 27.3) para dedup e matching
consistentes entre grafias diferentes do mesmo segmento (ex: "Construção
civil" vs "construcao civil").
"""

import unicodedata


def normalize_segment(segment: str) -> str:
    """Normaliza segmento para matching/dedup: lowercase + remove acentos + trim."""
    nfkd = unicodedata.normalize("NFKD", segment.lower().strip())
    return "".join(c for c in nfkd if not unicodedata.combining(c))
