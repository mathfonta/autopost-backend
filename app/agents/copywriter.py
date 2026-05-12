"""
Agente Copywriter — usa Claude Sonnet para gerar legenda, hashtags e CTA.

Responsabilidades:
- Criar legenda adaptada ao tom de voz e segmento do cliente
- Gerar hashtags: nicho + localização + gerais
- Sugerir CTA específico para o segmento
- Sugerir melhor horário de publicação
- NUNCA inventar dados — só usa o que está na análise da foto
"""

import json
import logging
import os

import anthropic

from app.cerebro.reader import read_patterns
from app.config import get_settings

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 2500
MAX_CAPTION_LONG_CHARS = 1500
MAX_CAPTION_SHORT_CHARS = 300
MAX_CAPTION_STORIES_CHARS = 150

# Horários de pico por segmento (fallback se Claude não sugerir)
_DEFAULT_TIMES = {
    "construção civil":    "18:00",
    "arquitetura":         "19:00",
    "saúde":               "07:00",
    "advogado":            "08:00",
    "dentista":            "12:00",
    "contador":            "08:00",
    "comércio":            "11:00",
    "default":             "19:00",
}

# Abordagem forçada por tentativa de retry — garante variação real
_RETRY_APPROACHES = {
    1: (
        "ABORDAGEM DESTA TENTATIVA: Foco total no RESULTADO e no benefício para o cliente. "
        "Não descreva o processo — destaque a transformação entregue e o problema resolvido. "
        "Seja direto e objetivo."
    ),
    2: (
        "ABORDAGEM DESTA TENTATIVA: Tom EMOCIONAL e aspiracional. "
        "Foque na conquista, no orgulho do trabalho bem feito, na satisfação do cliente. "
        "Humanize a empresa — mostre as pessoas por trás do serviço."
    ),
    3: (
        "ABORDAGEM DESTA TENTATIVA: Tom TÉCNICO e especialista. "
        "Destaque materiais utilizados, técnicas aplicadas e diferenciais de qualidade. "
        "Escreva como um profissional experiente falando para quem entende do assunto."
    ),
}

CONTENT_TYPE_PROMPTS = {
    "post_simples":    "Post direto apresentando o trabalho. Tom: profissional e claro.",
    "obra_andamento":  "Obra em progresso. Tom: transparência e confiança no processo.",
    "obra_concluida":  "Resultado final entregue. Tom: celebração, orgulho e resultado.",
    "engajamento":     "Post para gerar interação. Tom: pergunta direta, convite à participação.",
    "bastidores":      "Momento humano da equipe. Tom: autêntico, próximo, humanizado.",
    "before_after":    "Antes e depois da transformação. Tom: destaque a mudança, celebre o resultado.",
    "carousel":        "Série de imagens mostrando o trabalho. Tom: narrativa visual, conte a história.",
}

# Skill Library — 23 instruções de prompt por combinação formato+estratégia (Story 9.2)
STRATEGY_PROMPTS: dict[str, str] = {
    # ── Feed Photo (5) ──────────────────────────────────────────────
    "feed_photo__prova_social": (
        "ESTRATÉGIA: Prova Social Visual. "
        "Hook: 1 linha curta e direta com o resultado (ex: 'Entregue. ✓'). "
        "Corpo: 2-3 linhas contextualizando o trabalho realizado sem exagerar. "
        "CTA suave de contato ou orçamento. Emojis: máximo 2, funcionais."
    ),
    "feed_photo__ancora_de_marca": (
        "ESTRATÉGIA: Âncora de Marca. "
        "Hook: frase que reforça a identidade ou posicionamento da empresa. "
        "Corpo: 1-2 linhas sobre o que a marca representa ou entrega de diferente. "
        "CTA de reconhecimento — convide a seguir ou a conhecer mais. Emojis: 1-2."
    ),
    "feed_photo__curiosidade_pergunta": (
        "ESTRATÉGIA: Curiosidade + Pergunta. "
        "Hook: pergunta ou dado surpreendente do nicho que gera reflexão. "
        "Corpo: contexto rápido sobre o assunto. "
        "Encerre com outra pergunta convidando comentário. Tom: conversacional. Emojis: 2-3."
    ),
    "feed_photo__bastidores": (
        "ESTRATÉGIA: Bastidores. "
        "Hook: 'Por trás de...' ou 'O que ninguém vê antes de...'. "
        "Corpo: descreva o processo, a equipe ou o esforço por trás do trabalho. "
        "Tom: autêntico e humanizado. CTA: convide a acompanhar o processo. Emojis: 2-3."
    ),
    "feed_photo__hero_shot": (
        "ESTRATÉGIA: Hero Shot — destaque do produto ou serviço. "
        "Hook: nome do produto/serviço + adjetivo de impacto. "
        "Corpo: 1-2 benefícios concretos. CTA direto para orçamento ou compra. "
        "Tom: confiante e orientado à conversão. Emojis: 1-2."
    ),

    # ── Carousel (6) ────────────────────────────────────────────────
    "carousel__antes_depois": (
        "ESTRATÉGIA: Antes & Depois. "
        "Hook provocativo que destaca o contraste da transformação. "
        "Corpo: narrativa de transformação — mencione o problema inicial e o resultado final. "
        "CTA final: convide para conhecer o processo ou solicitar orçamento. "
        "Tom: storytelling emocional no início, técnico no meio, celebrativo no fim."
    ),
    "carousel__passo_a_passo": (
        "ESTRATÉGIA: Passo a Passo Educativo. "
        "Hook: promessa do que o leitor vai aprender (ex: 'X passos para...'). "
        "Corpo: introdução clara à sequência de slides. "
        "CTA: 'Salva esse post' ou 'Compartilha com quem precisa'. Tom: didático e acessível."
    ),
    "carousel__erros_mitos": (
        "ESTRATÉGIA: Erros / Mitos. "
        "Hook provocativo: 'X erros que...' ou 'Pare de acreditar que...'. "
        "Corpo: contexto do problema que o carrossel vai resolver. "
        "CTA: 'Desliza para não errar mais'. Tom: corretivo mas empático, nunca arrogante."
    ),
    "carousel__case_estudo": (
        "ESTRATÉGIA: Case / Estudo de Caso. "
        "Hook: apresente o cliente e o desafio inicial. "
        "Corpo: estrutura problema → solução → resultado com dados quando disponíveis. "
        "CTA: 'Quer o mesmo resultado? Me chama no DM'. Tom: técnico e confiável."
    ),
    "carousel__comparativo": (
        "ESTRATÉGIA: Comparativo. "
        "Hook: pergunta de escolha que engaja ('Qual você prefere?'). "
        "Corpo: introdução neutra ao comparativo dos slides. "
        "CTA: 'Desliza e decide' ou 'Comenta qual você escolheria'. Tom: neutro e informativo."
    ),
    "carousel__checklist": (
        "ESTRATÉGIA: Checklist / Guia de Referência. "
        "Hook: promessa de utilidade prática ('Salva antes de fechar'). "
        "Corpo: introdução à lista com o tema central. "
        "CTA obrigatório: 'Salva esse post — você vai querer rever'. Tom: utilitário e direto."
    ),

    # ── Reels (6) ───────────────────────────────────────────────────
    "reels__hook_choque": (
        "ESTRATÉGIA: Hook de Choque. "
        "LEGENDA (não o roteiro): deve complementar o vídeo, não repeti-lo. "
        "Hook da legenda: frase curta e provocativa (máx 10 palavras). "
        "Corpo: contexto mínimo do que o vídeo mostra. "
        "CTA: 'Segue para mais' ou pergunta aberta. Emojis: máximo 2 na legenda."
    ),
    "reels__timelapse": (
        "ESTRATÉGIA: Timelapse / Transformação Visual. "
        "LEGENDA: o vídeo fala por si — a legenda é enxuta e descritiva. "
        "Hook: dado concreto ('De 0 a entregue em X dias'). "
        "Corpo: 1 linha de contexto. CTA: convite para orçamento ou DM. Emojis: 1-2."
    ),
    "reels__tutorial_pov": (
        "ESTRATÉGIA: Tutorial POV. "
        "LEGENDA: configure o POV com 1 frase ('POV: você...'). "
        "Corpo: 1-2 linhas do que o vídeo demonstra. "
        "CTA: 'Comenta se quiser ver mais' ou 'DM aberto'. Tom: demonstrativo e próximo."
    ),
    "reels__trend_nicho": (
        "ESTRATÉGIA: Trend + Nicho. "
        "LEGENDA: tom leve e atual, adaptado à tendência usada no vídeo. "
        "Hook: adapte a frase do trend ao nicho de forma criativa. "
        "CTA: 'Salva' ou 'Marca alguém que precisa ver isso'. Emojis: 3-4, mais descontraídos."
    ),
    "reels__bastidores_autenticos": (
        "ESTRATÉGIA: Bastidores Autênticos. "
        "LEGENDA: confessional e honesta — 'Ninguém mostra isso. Mas eu vou mostrar.' "
        "Corpo: 2 linhas sobre o que o vídeo revela do processo real. "
        "CTA: 'Segue para acompanhar'. Tom: vulnerável no início, confiante no fim."
    ),
    "reels__depoimento_video": (
        "ESTRATÉGIA: Depoimento em Vídeo. "
        "LEGENDA: inicie com uma citação real ou paráfrase do cliente (entre aspas). "
        "Corpo: contexto breve do resultado que motivou o depoimento. "
        "CTA: 'Quer o mesmo? Link na bio'. Tom: prova social, genuíno."
    ),

    # ── Story (6) ───────────────────────────────────────────────────
    "story__bastidores_dia": (
        "ESTRATÉGIA: Bastidores do Dia. "
        "Texto curto e informal para sobrepor na imagem — máx 10 palavras. "
        "Tom: conversacional e imediato, como se estivesse falando com um amigo. "
        "Sem hashtags em Stories. CTA: sticker de resposta ou pergunta rápida."
    ),
    "story__enquete": (
        "ESTRATÉGIA: Enquete. "
        "Escreva 1 pergunta direta + 2 opções simples para o sticker de enquete. "
        "Tom: descontraído. Sem hashtags. Texto principal: máx 8 palavras. "
        "Formato de entrega: inclua 'OPÇÃO A: ...' e 'OPÇÃO B: ...' no copy."
    ),
    "story__cta_link": (
        "ESTRATÉGIA: CTA + Link. "
        "Contexto em 1 frase + benefício direto + instrução clara para o link. "
        "Tom: urgente e sem rodeios. Máx 15 palavras no texto principal. "
        "Use seta ou dedo apontando no copy (ex: '👇 Clica aqui'). Sem hashtags."
    ),
    "story__countdown": (
        "ESTRATÉGIA: Countdown / Urgência. "
        "Título de urgência em destaque + contexto da oferta ou prazo. "
        "Tom: escassez genuína — não exagere. Máx 12 palavras. "
        "Inclua instrução para o sticker de countdown. Sem hashtags."
    ),
    "story__caixa_perguntas": (
        "ESTRATÉGIA: Caixa de Perguntas. "
        "Convite aberto e acolhedor para perguntas sobre o tema da imagem. "
        "Ex: 'Me manda sua dúvida sobre [tema] — respondo aqui'. Máx 15 palavras. "
        "Tom: especialista acessível. Sem hashtags."
    ),
    "story__repost_feed": (
        "ESTRATÉGIA: Repost do Feed. "
        "Complemento casual ao post que está sendo re-compartilhado. "
        "Ex: 'Você viu esse post?' ou 'Acabei de postar — não deixa de ver'. "
        "Tom: conversa direta. Máx 10 palavras. Sem hashtags."
    ),
}

_SYSTEM_PROMPT = """\
Você é um especialista em copywriting viral para redes sociais de pequenas empresas brasileiras.
Crie 3 variações de legenda para Instagram baseadas EXCLUSIVAMENTE nas informações fornecidas.

REGRAS OBRIGATÓRIAS:
1. NUNCA invente dados, medidas, valores, prazos ou informações não presentes na descrição
2. Use o tom de voz e segmento do cliente fornecidos
3. As 3 variações devem ter abordagens COMPLETAMENTE diferentes — hook diferente, estrutura diferente, ângulo diferente
4. PARÁGRAFOS OBRIGATÓRIOS em caption_long: separe cada bloco com \\n\\n no JSON. NUNCA escreva caption_long como bloco único. Mínimo 3 parágrafos.
5. NUNCA comece a legenda com o nome da empresa, "Confira", "Olha" ou "Veja".

6. HOOK OBRIGATÓRIO — A PRIMEIRA FRASE PARA O SCROLL (máx 10 palavras):
   Adapte uma das estruturas ao conteúdo real disponível:
   - Situação inesperada: "A cliente trouxe a peça errada. Veja o que fizemos 👇"
   - Pergunta-espelho: "Você sabia que [fato surpreendente do nicho]?"
   - Número concreto: "3 horas. Um resultado que o cliente não esperava."
   - Contraste: "Parecia impossível. Mas ficou assim 🏠"
   - Revelação: "Ninguém fala sobre o que acontece quando [situação real do serviço]."

7. RITMO VISUAL OBRIGATÓRIO:
   Alterne frases curtas (5–8 palavras) com frases médias (10–15 palavras).
   Máximo 3 linhas por parágrafo. O espaço em branco é descanso visual — use-o.

8. EMOJIS — POSICIONAMENTO PRECISO:
   - 1 emoji no hook (funcional, reflete o conteúdo — nunca decorativo)
   - 1 emoji por parágrafo do desenvolvimento
   - 1–2 emojis no CTA
   - Total: 4–7 emojis por caption_long
   - NUNCA emoji sozinho numa linha. NUNCA mais de 2 emojis seguidos.

9. CTA COM AÇÃO IMEDIATA (nunca use "Entre em contato" genérico):
   Use versões conversacionais e específicas:
   - "Me chama no DM e conta o seu projeto 💬"
   - "Comenta aqui: qual seria o seu maior desafio nisso? 👇"
   - "Salva esse post para quando precisar 📌"
   - "Link na bio para solicitar orçamento 🔗"
   - "Me fala nos comentários como está o seu projeto 👇"

QUALIDADE DA LEGENDA LONGA (caption_long):
- Escreva até 1500 caracteres — use o espaço disponível
- Estrutura obrigatória: HOOK scroll-stopper (≤10 palavras) → contexto/problema → processo/solução → resultado → CTA
- Use quebras de parágrafo (\\n\\n entre parágrafos)
- Seja específico: mencione materiais, técnicas, detalhes do serviço quando disponíveis
- Tom storytelling — conte o que aconteceu, não apenas descreva a foto

QUALIDADE DA LEGENDA CURTA (caption_short):
- Até 300 chars — seja rico dentro do limite
- Hook direto + resultado concreto + CTA mínimo

Responda EXCLUSIVAMENTE em JSON válido, sem texto fora do JSON:
{
  "caption_long": "<hook scroll-stopper ≤10 palavras>\\n\\n<contexto ou problema>\\n\\n<processo ou solução>\\n\\n<resultado + CTA>",
  "caption_short": "<versão objetiva e direta, até 300 chars, sem hashtags>",
  "caption_stories": "<texto para Stories, tom conversacional e imediato, até 150 chars>",
  "hashtags": ["hashtag1", "hashtag2", ...],
  "cta": "<call-to-action conversacional, ex: Me chama no DM e conta o seu projeto 💬>",
  "suggested_time": "<HH:MM — melhor horário para publicar para este segmento>"
}

Regras das hashtags:
- Entre 10 e 20 hashtags (aplicam-se às 3 variações)
- Inclua hashtags do nicho (ex: #construcaocivil), da localização (ex: #florianopolis) e gerais (#instagram #brasil)
- Sem o símbolo # no JSON — apenas a palavra
- Todas em minúsculo, sem espaços, sem acentos
"""

_VOICE_TONE_MAP = {
    "formal":    "tom formal, profissional e aspiracional",
    "casual":    "tom descontraído, próximo e direto",
    "technical": "tom técnico, preciso e informativo",
}

# Bloco estático da skill library — cacheado via prompt caching Anthropic (cache_control ephemeral).
# Inclui todas as estratégias, intenções e mapeamentos para atingir o mínimo de 1024 tokens.
# Cache hit: 90% de desconto nos tokens deste bloco. Cache TTL: 5 minutos.
_VIRAL_TRIGGERS = {
    "construção civil": (
        "Solução criativa para problema inesperado | "
        "Prazo cumprido contra expectativa | "
        "Transformação dramática antes/depois | "
        "Bastidores: o que acontece antes da entrega | "
        "Material adaptado que superou o padrão"
    ),
    "arquitetura": (
        "Projeto de meses revelado em um post | "
        "Espaço sem solução aparente transformado | "
        "Detalhe técnico invisível que faz toda diferença | "
        "Cliente que não acreditava no resultado"
    ),
    "saúde": (
        "Medo transformado em confiança | "
        "Resultado visível que o paciente não esperava | "
        "Desmistificar procedimento temido | "
        "Cuidado que muda qualidade de vida"
    ),
    "dentista": (
        "Sorriso que o paciente adiou por anos | "
        "Tecnologia que não dói | "
        "Antes/depois impactante | "
        "Dúvida comum respondida com clareza"
    ),
    "comércio": (
        "Produto com história por trás | "
        "Bastidores da produção ou seleção | "
        "Promoção com prazo real e urgência genuína | "
        "Cliente satisfeito com resultado inesperado"
    ),
    "default": (
        "Situação inesperada que virou solução | "
        "Resultado que superou expectativa do cliente | "
        "Bastidores do processo que ninguém vê | "
        "Antes/depois da transformação entregue"
    ),
}

_STATIC_LIBRARY = (
    "=== BIBLIOTECA DE ESTRATÉGIAS (referência para uso conforme instrução) ===\n\n"
    "GATILHOS VIRAIS POR NICHO (use para construir o hook e o desenvolvimento):\n"
    + "\n".join(f"[{k}] {v}" for k, v in _VIRAL_TRIGGERS.items())
    + "\n\nESTRATÉGIAS DISPONÍVEIS:\n"
    + "\n".join(f"[{k}]\n{v}" for k, v in STRATEGY_PROMPTS.items())
    + "\n\nINTENÇÕES DE CONTEÚDO (LEGADO):\n"
    + "\n".join(f"[{k}] {v}" for k, v in CONTENT_TYPE_PROMPTS.items())
    + "\n\nTONS DE VOZ:\n"
    + "\n".join(f"[{k}] {v}" for k, v in _VOICE_TONE_MAP.items())
    + "\n\nABORDAGENS DE RETRY:\n"
    + "\n".join(f"[tentativa_{k}] {v}" for k, v in _RETRY_APPROACHES.items())
    + "\n\n=== FIM DA BIBLIOTECA ===\n"
)


async def _call_gemini_for_copy(user_message: str) -> str:
    """Chama Gemini 2.5 Flash para gerar copy — provider alternativo ao Claude."""
    from google import genai

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("[copywriter/gemini] GEMINI_API_KEY não configurada")

    client = genai.Client(api_key=api_key)
    full_prompt = f"{_SYSTEM_PROMPT}\n\n{_STATIC_LIBRARY}\n\n{user_message}"

    response = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=[full_prompt],
    )
    return (response.text or "").strip()


async def generate_copy_with_ai(
    analysis_result: dict,
    brand_profile: dict,
    user_content_type: str | None = None,
    strategy: str | None = None,
    user_context: str | None = None,
    voice_tone: str | None = None,
    retry_attempt: int = 0,
) -> dict:
    """
    Gera legenda, hashtags e CTA para o post usando Claude Sonnet.

    Args:
        analysis_result: Output do Agente Analista (description, content_type, stage)
        brand_profile: Perfil de marca do cliente (segment, tone, city, company_name)

    Returns:
        dict com: caption (= caption_long), caption_long, caption_short, caption_stories, hashtags, cta, suggested_time

    Raises:
        anthropic.APITimeoutError: se Claude não responder em 30s
        ValueError: se resposta não for JSON válido
    """
    settings = get_settings()
    provider = settings.COPY_PROVIDER.lower()

    # Monta contexto do cliente
    segment = brand_profile.get("segment", "empresa")
    tone = brand_profile.get("tone", "profissional")
    city = brand_profile.get("city", "")
    company = brand_profile.get("company_name", "")

    # Monta informações da(s) foto(s) — suporte multi-foto
    photos = analysis_result.get("photos")
    if photos:
        descriptions = [p.get("description", "") for p in photos if p.get("description")]
        description = f"Sequência de {len(photos)} fotos: " + "; ".join(descriptions) if descriptions else "Série de fotos do trabalho"
        content_type = analysis_result.get("content_type", "obra_realizada")
        stage = analysis_result.get("stage", "")
    else:
        description = analysis_result.get("description", "Foto do trabalho realizado")
        content_type = analysis_result.get("content_type", "obra_realizada")
        stage = analysis_result.get("stage", "")

    content_type_labels = {
        "obra_realizada": "foto de obra/serviço realizado",
        "antes_depois":   "antes e depois de reforma/serviço",
        "dica":           "dica ou conteúdo educativo",
        "promocao":       "promoção ou oferta especial",
        "outro":          "conteúdo diverso",
    }
    content_label = content_type_labels.get(content_type, content_type)

    # Injeta padrões do cérebro local (horário e CTA comprovados)
    patterns = read_patterns()
    patterns_section = ""
    if patterns:
        patterns_section = (
            f"\n\nPADRÕES COMPROVADOS PARA ESTE CLIENTE:\n{patterns}\n\n"
            "Use o horário e CTA sugeridos pelos padrões como referência prioritária."
        )

    # Injeta sub-estratégia da Skill Library (Story 9.2) — tem precedência sobre content_type legado
    strategy_section = ""
    if strategy and user_content_type:
        skill_key = f"{user_content_type}__{strategy}"
        skill_instruction = STRATEGY_PROMPTS.get(skill_key, "")
        if skill_instruction:
            strategy_section = f"\n\n{skill_instruction}"

    # Injeta intenção do cliente se fornecida (fallback legado quando sem strategy)
    intent_section = ""
    if user_content_type and user_content_type in CONTENT_TYPE_PROMPTS and not strategy_section:
        intent_section = f"\nINTENÇÃO DO CLIENTE: {CONTENT_TYPE_PROMPTS[user_content_type]}"

    # Injeta tom de voz configurado pelo usuário
    effective_tone = _VOICE_TONE_MAP.get(voice_tone or "", "") if voice_tone else ""
    voice_tone_section = ""
    if effective_tone:
        voice_tone_section = f"\n#TOM_DE_VOZ: {effective_tone}"

    # Injeta contexto do usuário (especificação de material, serviço, produto)
    user_context_section = ""
    music_section = ""
    if user_context and user_context.strip():
        # Extrai música de fundo do contexto se presente
        lines = user_context.strip().splitlines()
        music_line = next((l for l in lines if l.startswith("Música de fundo:")), None)
        other_lines = [l for l in lines if not l.startswith("Música de fundo:")]
        pure_context = "\n".join(other_lines).strip()

        if music_line:
            song = music_line.replace("Música de fundo:", "").strip()
            music_section = (
                f"\n\nMÚSICA DE FUNDO SELECIONADA: {song}\n"
                "INSTRUÇÃO OBRIGATÓRIA: inclua a música no final de caption_long e caption_short "
                f"neste formato exato: 🎵 {song}"
            )
        if pure_context:
            user_context_section = (
                f"\n\nCONTEXTO DO CLIENTE (use para enriquecer — não substitui o que você vê na foto):\n"
                f"{pure_context}"
            )

    # Injeta transcrição do áudio se disponível (Reels com narração)
    transcript_section = ""
    if analysis_result.get("audio_transcript"):
        transcript_section = (
            f"\n\nTRANSCRIÇÃO DO ÁUDIO (profissional narrou durante o vídeo):\n"
            f"{analysis_result['audio_transcript']}\n"
            "USE a transcrição como contexto principal — ela revela o que realmente aconteceu."
        )

    # Injeta gatilhos virais do nicho para guiar o hook
    segment_key = segment.lower().strip()
    viral_triggers = _VIRAL_TRIGGERS.get(segment_key, _VIRAL_TRIGGERS["default"])
    viral_section = f"\n\nGATILHOS VIRAIS DO NICHO — use um destes ângulos para o hook:\n{viral_triggers}"

    # Injeta abordagem forçada para garantir variação real no retry
    retry_section = ""
    if retry_attempt > 0:
        approach = _RETRY_APPROACHES.get(retry_attempt, _RETRY_APPROACHES[3])
        retry_section = f"\n\n{approach}"

    # Campos enriquecidos do analista (novos — podem estar ausentes em posts antigos)
    elementos = analysis_result.get("elementos_visuais", "")
    ambiente = analysis_result.get("ambiente", "")
    nivel = analysis_result.get("nivel_acabamento", "")
    extra_section = ""
    if elementos or ambiente or nivel:
        extra_section = (
            f"\n- Elementos visuais: {elementos or 'não identificados'}"
            f"\n- Ambiente: {ambiente or 'não identificado'}"
            f"\n- Nível de acabamento: {nivel or 'não identificado'}"
        )

    user_message = f"""
Crie uma legenda para este post:

CLIENTE:
- Empresa: {company or segment}
- Segmento: {segment}
- Tom de voz: {tone}
- Cidade: {city or "não informada"}{voice_tone_section}

FOTO:
- Tipo: {content_label}
- Descrição: {description}
- Etapa/detalhe: {stage or "não informado"}{extra_section}{user_context_section}{transcript_section}{music_section}{viral_section}{strategy_section}{intent_section}{patterns_section}{retry_section}
"""

    logger.info(f"[copywriter] provider={provider} segment={segment} content_type={content_type} strategy={strategy or 'none'} retry_attempt={retry_attempt} audio_transcript={'sim' if transcript_section else 'não'}")

    if provider == "gemini":
        raw = await _call_gemini_for_copy(user_message)
    else:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        message = await client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            timeout=30.0,
            system=[{"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _STATIC_LIBRARY, "cache_control": {"type": "ephemeral"}},
                        {"type": "text", "text": user_message},
                    ],
                }
            ],
            extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
        )
        raw = message.content[0].text.strip()

    logger.info(f"[copywriter] resposta bruta ({provider}): {raw[:200]}")

    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[-2] if "```" in cleaned[3:] else cleaned[3:]
            cleaned = cleaned.lstrip("json").strip()
        result = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"[copywriter/{provider}] JSON inválido: {raw[:300]}") from e

    # Backward compat: se Claude retornou formato antigo (só caption)
    if "caption" in result and "caption_long" not in result:
        result["caption_long"] = result["caption"]
        result["caption_short"] = None
        result["caption_stories"] = None

    # Garante campos com defaults
    result.setdefault("caption_long", "")
    result.setdefault("caption_short", None)
    result.setdefault("caption_stories", None)
    result.setdefault("hashtags", [])
    result.setdefault("cta", "Entre em contato pelo link na bio!")
    result.setdefault("suggested_time", _DEFAULT_TIMES.get(segment.lower().strip(), _DEFAULT_TIMES["default"]))

    # Trunca variações nos limites
    if result["caption_long"] and len(result["caption_long"]) > MAX_CAPTION_LONG_CHARS:
        result["caption_long"] = result["caption_long"][:MAX_CAPTION_LONG_CHARS - 3] + "..."
    if result["caption_short"] and len(result["caption_short"]) > MAX_CAPTION_SHORT_CHARS:
        result["caption_short"] = result["caption_short"][:MAX_CAPTION_SHORT_CHARS - 3] + "..."
    if result["caption_stories"] and len(result["caption_stories"]) > MAX_CAPTION_STORIES_CHARS:
        result["caption_stories"] = result["caption_stories"][:MAX_CAPTION_STORIES_CHARS - 3] + "..."

    # caption principal = caption_long (para publicação e retrocompat)
    result["caption"] = result["caption_long"] or ""

    # Normaliza hashtags: remove # se presente, lowercase, sem espaços
    result["hashtags"] = [
        h.lstrip("#").lower().replace(" ", "")
        for h in result["hashtags"]
        if h.strip()
    ]

    logger.info(
        f"[copywriter] caption_long={len(result['caption_long'])} chars "
        f"caption_short={len(result['caption_short'] or '')} chars "
        f"caption_stories={len(result['caption_stories'] or '')} chars "
        f"hashtags={len(result['hashtags'])} "
        f"time={result['suggested_time']}"
    )

    return result
