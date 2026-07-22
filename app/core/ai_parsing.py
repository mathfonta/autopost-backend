"""
Helpers de parsing de respostas de LLM compartilhados entre agentes (analyst,
copywriter, theme_generator). Extraído para evitar duplicação da limpeza de
markdown code fences antes do json.loads.
"""


def strip_json_fences(raw: str) -> str:
    """
    Remove code fences markdown (```json ... ``` ou ``` ... ```) que o
    modelo às vezes envolve ao redor de uma resposta JSON.

    Idempotente para strings que já não têm fences.
    """
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[-2] if "```" in cleaned[3:] else cleaned[3:]
        cleaned = cleaned.lstrip("json").strip()
    return cleaned
