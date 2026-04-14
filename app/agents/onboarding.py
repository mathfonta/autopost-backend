"""
Agente Onboarding — Claude Sonnet conduz conversa estruturada para coletar
o brand_profile do cliente (nome, segmento, cidade, tom de voz, cor, Instagram).

Sessão armazenada no Redis com TTL de 24h.
Quando todos os campos obrigatórios são coletados, Claude emite PROFILE_COMPLETE
seguido de um JSON com o brand_profile completo.
"""

import json
import logging
import re

import anthropic

from app.config import get_settings
from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 500
ONBOARDING_TTL = 24 * 3600  # 24 horas

_SYSTEM_PROMPT = """\
Você é o assistente de boas-vindas do AutoPost, uma plataforma que cria conteúdo automaticamente para Instagram e Facebook de pequenas empresas brasileiras.

Sua tarefa é coletar informações sobre a empresa do cliente de forma conversacional e amigável — como um consultor simpático, não um formulário.

Colete obrigatoriamente (nesta ordem sugerida):
1. Nome da empresa ou profissional autônomo
2. Segmento de atuação — escolha o mais próximo: construção civil, arquitetura, saúde, dentista, advogado, contador, comércio, outro
3. Cidade principal de atuação
4. Tom de voz para as postagens — escolha: profissional, casual, próximo, inspirador

Colete opcionalmente:
5. Cor primária da marca (se souber — ex: "azul marinho" ou código hex como #1A3C6E)
6. Se já tem perfil Instagram profissional (sim/não)

Regras:
- Faça uma pergunta por vez, de forma natural
- Se a resposta for vaga para segmento, sugira o mais próximo e confirme
- Não repita perguntas já respondidas
- Quando tiver os 4 campos obrigatórios, faça um resumo e peça confirmação
- Após confirmação (ou se o usuário disser "está certo" / "sim"), emita EXATAMENTE:

PROFILE_COMPLETE
{"company_name": "...", "segment": "...", "city": "...", "tone": "...", "primary_color": null, "has_instagram": null}

Substitua null pelos valores coletados se disponíveis. Nunca invente dados.
"""

_OPENING_MESSAGE = (
    "Olá! Bem-vindo ao AutoPost! 🎉\n\n"
    "Sou o assistente de configuração da plataforma. "
    "Vou precisar de alguns dados sobre sua empresa para personalizar o conteúdo — "
    "não vai demorar mais de 2 minutinhos.\n\n"
    "Para começar: qual é o nome da sua empresa ou como você se chama profissionalmente?"
)


# ─── Sessão Redis ────────────────────────────────────────────────────────────

async def get_session(client_id: str) -> dict | None:
    redis = await get_redis()
    data = await redis.get(f"onboarding:{client_id}")
    return json.loads(data) if data else None


async def save_session(client_id: str, session: dict) -> None:
    redis = await get_redis()
    await redis.setex(f"onboarding:{client_id}", ONBOARDING_TTL, json.dumps(session))


async def delete_session(client_id: str) -> None:
    redis = await get_redis()
    await redis.delete(f"onboarding:{client_id}")


def _new_session() -> dict:
    return {"messages": [], "done": False, "brand_profile": None}


# ─── Extração do brand_profile ───────────────────────────────────────────────

def _extract_profile(text: str) -> dict | None:
    """Extrai JSON do brand_profile após o marcador PROFILE_COMPLETE."""
    match = re.search(r"PROFILE_COMPLETE\s*(\{.*?\})", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        logger.warning(f"[onboarding] PROFILE_COMPLETE com JSON inválido: {text[:200]}")
        return None


# ─── Chamada ao Claude ───────────────────────────────────────────────────────

async def _call_claude(messages: list[dict]) -> str:
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = await client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        timeout=30.0,
        system=_SYSTEM_PROMPT,
        messages=messages,
    )
    return response.content[0].text.strip()


# ─── API pública do agente ───────────────────────────────────────────────────

async def start_session(client_id: str) -> dict:
    """
    Inicia (ou reinicia) sessão de onboarding.
    Retorna a mensagem de abertura sem chamar Claude na primeira vez.
    """
    session = _new_session()
    session["messages"].append({
        "role": "assistant",
        "content": _OPENING_MESSAGE,
    })
    await save_session(client_id, session)
    logger.info(f"[onboarding] sessão iniciada client_id={client_id}")
    return {"last_message": _OPENING_MESSAGE, "done": False}


async def process_message(client_id: str, user_message: str) -> dict:
    """
    Processa mensagem do usuário e retorna a resposta do Claude.

    Returns:
        dict com: reply (str), done (bool), brand_profile (dict|None)
    """
    session = await get_session(client_id)
    if session is None:
        # Sessão expirada — reinicia automaticamente
        session = _new_session()
        session["messages"].append({
            "role": "assistant",
            "content": _OPENING_MESSAGE,
        })

    if session.get("done"):
        return {
            "reply": "Seu perfil já está configurado! Para alterar, inicie um novo onboarding.",
            "done": True,
            "brand_profile": session.get("brand_profile"),
        }

    # Adiciona mensagem do usuário
    session["messages"].append({"role": "user", "content": user_message})

    # Chama Claude com o histórico completo
    reply = await _call_claude(session["messages"])
    session["messages"].append({"role": "assistant", "content": reply})

    # Verifica se onboarding foi concluído
    brand_profile = _extract_profile(reply)
    if brand_profile:
        session["done"] = True
        session["brand_profile"] = brand_profile
        # Remove marcador técnico da resposta exibida ao usuário
        clean_reply = re.sub(r"PROFILE_COMPLETE\s*\{.*?\}", "", reply, flags=re.DOTALL).strip()
        reply = clean_reply or "Perfeito! Seu perfil está configurado e pronto para criar conteúdo. 🚀"
        logger.info(f"[onboarding] concluído client_id={client_id} segment={brand_profile.get('segment')}")

    await save_session(client_id, session)

    return {
        "reply": reply,
        "done": session["done"],
        "brand_profile": brand_profile,
    }
