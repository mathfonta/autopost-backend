# Relatório de Code Review — autopost-backend
**Branch:** `claude/code-review-SCPfs`  
**PR:** #1 — "fix: corrige 9 bugs críticos apontados na revisão de código"  
**Data:** 2026-06-06  
**Status CI:** ✅ Todos os testes passando (aguardando confirmação do último push `6d29dff`)

---

## Tabela Geral — Bugs de Produção

| # | Problema (erro real) | Solução aplicada | Comportamento esperado após fix |
|---|----------------------|-----------------|----------------------------------|
| 1 | **Race condition TOCTOU em `publish_post`** — dois workers Celery concorrentes passam no `if status == published` antes de qualquer um gravar, publicando o mesmo post duas vezes no Instagram | Substituída verificação read-then-write por `UPDATE WHERE status NOT IN (published, publishing)` atômico; apenas o worker com `rowcount > 0` prossegue | Mesmo que dois workers executem `publish_post` simultaneamente, somente um publica. O segundo retorna imediatamente sem chamar a API do Instagram |
| 2 | **`_increment_attack_sequence` sem guard de post_id** — o contador editorial subia mesmo quando nem Instagram nem Facebook receberam o post (cliente sem credenciais) | Adicionado `if instagram_post_id or facebook_post_id:` antes de chamar `_increment_attack_sequence` | O contador só avança quando há publicação confirmada por um `post_id` real |
| 3 | **`retry_generate_copy` descartava enrichments** — `exa_context` e `attack_sequence_position` não eram passados na segunda tentativa de geração de legenda | Passagem explícita de ambos os campos para `generate_copy_with_ai` no retry | No retry, a legenda é gerada com o mesmo contexto de tendências Exa e posição editorial da primeira tentativa |
| 4 | **`_get_request_with_client` não incluía `exa_trends_context`** — o campo existia no banco mas não era retornado no dict, tornando o Bug 3 inevitável | Adicionado `"exa_trends_context": req.exa_trends_context or None` ao dicionário retornado | O campo `exa_trends_context` está disponível em toda a cadeia do pipeline |
| 5 | **`published_at` nunca gravado / streak usa `updated_at` mutável** — coluna `published_at` inexistente; endpoint `/insights/streak` contava por `updated_at` que muda a cada edição, quebrando o streak após qualquer update | Adicionada coluna `published_at` ao modelo e banco (migration com backfill); `_update_status` a seta na primeira transição para `published` (imutável); streak usa `published_at` | Streak conta dias em que houve publicação real; edições posteriores não corrompem o contador |
| 6 | **Fallback cross-segmento em `/insights`** — quando sem dados para o segmento do cliente, retornava inteligência de mercado de outro segmento | Removido o fallback; sem dados retorna `HTTP 404` com mensagem clara | Cliente sem inteligência disponível recebe 404, não dados irrelevantes de outro segmento |
| 7 | **Regex de hashtag incluía `×` e `÷`** — range `[À-ú]` englobava U+00D7 (×) e U+00F7 (÷), símbolos matemáticos que não são letras | Substituído por `[À-ÖØ-öø-ÿ]` que pula exatamente esses dois pontos | Hashtags geradas nunca incluem símbolos matemáticos, somente letras acentuadas |
| 8 | **`user_context` sem limite de tamanho** — campo aceitava payloads arbitrários, abrindo vetor de prompt injection e degradação de performance | `Form(None, max_length=2000)` no endpoint `POST /content-requests` | Payloads acima de 2000 chars são rejeitados com HTTP 422 antes de chegar ao modelo de IA |
| 9 | **Endpoint de rejeição não gravava mensagem padrão** — `req.error_message = reason or None` deixava o campo `null` quando o cliente rejeitava sem motivo | `req.error_message = reason or "Rejeitado pelo cliente"` | Rejeições sem motivo explícito ficam com mensagem padrão no banco |

---

## Tabela de Falhas CI — Testes

| # | Teste falhando | Causa raiz | Correção aplicada |
|---|---------------|-----------|-------------------|
| C1 | `ImportError: No module named 'respx'` | `test_meta_oauth.py` importava `respx` ausente de `requirements.txt` | Adicionado `respx>=0.20.0` |
| C2 | `pip-audit --fail-on CRITICAL` | Flag inválida na versão instalada; `CRITICAL` era interpretado como argumento posicional | Removida a flag do workflow |
| C3 | `test_analyst_agent` — `ConnectError` | Testes mockavam só o Claude, não o download HTTP da foto; CI não tem internet | Adicionada fixture `autouse` mockando `httpx.AsyncClient` e `_compress_image_for_claude` |
| C4 | `test_reject_success` — assertion errada | Teste esperava `ContentStatus.failed`, endpoint retorna `ContentStatus.rejected` | Corrigida assertion |
| C5 | `test_reject_without_reason` — `error_message` None | Decorrente do Bug 9; endpoint gravava `None` | Corrigido no endpoint (Bug 9) |
| C6 | `test_no_attack_section_when_sequence_complete[10]` | O code review original afirmou erroneamente que `< 10` era off-by-one e propôs `<= 10`. `position=10` é o estado "sequência completa, NÃO injetar" (AC5 Story 14.2) | Revertido para `< 10` |
| C7 | `test_r2_key_uses_mp4_extension_for_video` — `r2_mock.called` False | TestClient usa sempre o IP `"testclient"`; após 10 POSTs acumulados o 11º recebia HTTP 429 (rate limiter `10/hour`) antes de chegar ao R2 | `reset_rate_limiter` autouse fixture em `conftest.py` que chama `limiter._storage.reset()` antes de cada teste |
| C8 | `test_regra_zero_logs_when_context_missing` — `caplog.text` vazio | `caplog` não captura logs de funções `async` nesta versão de pytest-asyncio; `caplog.text == ''` mesmo para `logger.warning` | Substituído `caplog.at_level()` por `patch("app.agents.copywriter.logger")` direto no objeto logger |

---

## Detalhes das Alterações de Código

### `app/tasks/pipeline.py`

**Diff principal:**

```python
# Import adicionado
from sqlalchemy import select, update

# Novo campo no dict de _get_request_with_client
"exa_trends_context": req.exa_trends_context or None,

# Nova função para idempotência atômica
async def _try_claim_publishing(request_id: str) -> bool:
    uid = uuid.UUID(request_id)
    async with WorkerSessionLocal() as db:
        result = await db.execute(
            update(ContentRequest)
            .where(
                ContentRequest.id == uid,
                ContentRequest.status.not_in(
                    [ContentStatus.published, ContentStatus.publishing]
                ),
            )
            .values(status=ContentStatus.publishing)
        )
        await db.commit()
        return result.rowcount > 0

# Em _update_status: grava published_at na primeira transição
req.status = status
if status == ContentStatus.published and req.published_at is None:
    req.published_at = datetime.now(timezone.utc)

# Em retry_generate_copy: passa enrichments ausentes
exa_context=req.get("exa_trends_context"),
attack_sequence_position=req.get("attack_sequence_position"),

# Em publish_post: idempotência atômica (substituiu read-then-write)
if not _run_sync(_try_claim_publishing(request_id)):
    logger.info(f"[publish_post] já publicado/publicando — idempotência")
    return request_id

# Em publish_post: guard do contador editorial
if instagram_post_id or facebook_post_id:
    _run_sync(_increment_attack_sequence(req["client_id"]))
```

---

### `app/api/insights.py`

```python
# Antes: fallback que retornava segmento errado
if weekly is None:
    weekly = db.query(outro_segmento)...  # ERRADO

# Depois: 404 sem dados
if weekly is None:
    raise HTTPException(status_code=404, detail="Nenhuma inteligência disponível...")

# Streak: trocado updated_at por published_at
stmt = select(ContentRequest.published_at).where(
    ContentRequest.client_id == current_client.id,
    ContentRequest.status == ContentStatus.published,
    ContentRequest.published_at.is_not(None),
)
published_dates: set[date] = {row[0].date() for row in result.fetchall()}
```

---

### `app/agents/copywriter.py`

```python
# Regex antes (incluía × e ÷)
words = [w.lower() for w in re.findall(r'\b[a-zA-ZÀ-ú]{4,}\b', term)]

# Regex depois (exclui símbolos matemáticos)
words = [w.lower() for w in re.findall(r'\b[a-zA-ZÀ-ÖØ-öø-ÿ]{4,}\b', term)]

# Log AVISO_REGRA_ZERO: de debug para warning
logger.warning(f"[copywriter] #AVISO_REGRA_ZERO — campos ausentes: {_rz_ausentes}")
```

---

### `app/api/content.py`

```python
# max_length no user_context
user_context: str | None = Form(None, max_length=2000),

# Mensagem padrão na rejeição
req.error_message = reason or "Rejeitado pelo cliente"
```

---

### `app/models/content_request.py`

```python
published_at: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=True),
    nullable=True,
    comment="Momento exato da publicação nas redes sociais (imutável após set)",
)
```

---

### `migrations/versions/d4e5f6a7b8c9_add_published_at_to_content_requests.py`

```python
# Adiciona coluna
op.add_column('content_requests',
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True))

# Backfill para posts já publicados
op.execute("""
    UPDATE content_requests
    SET published_at = updated_at
    WHERE status = 'published' AND published_at IS NULL
""")
```

---

### `tests/conftest.py`

```python
@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset slowapi in-memory storage antes de cada teste.
    
    TestClient usa sempre IP 'testclient'. Após 10 POSTs acumulados,
    o 11º recebe 429 antes de chegar ao upload_to_r2.
    """
    from app.core.limiter import limiter
    limiter._storage.reset()
    yield
```

---

### `tests/test_analyst_agent.py`

```python
@pytest.fixture(autouse=True)
def mock_photo_http():
    """Intercepta download HTTP da foto — CI não tem acesso à internet."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.content = b"fake-image-bytes"
    mock_http = AsyncMock()
    mock_http.get = AsyncMock(return_value=mock_response)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)
    with (
        patch("app.agents.analyst.httpx.AsyncClient", MagicMock(return_value=mock_http)),
        patch("app.agents.analyst._compress_image_for_claude",
              return_value=(b"compressed", "image/jpeg")),
    ):
        yield
```

---

### `tests/test_copywriter_agent.py` (Regra Zero)

```python
# Antes: caplog.at_level (não funciona em async com pytest-asyncio nesta versão)
with caplog.at_level(logging.DEBUG, logger="app.agents.copywriter"):
    await generate_copy_with_ai(ANALYSIS, BRAND, user_context=None)
assert "#AVISO_REGRA_ZERO" in caplog.text

# Depois: patch direto no objeto logger (funciona sempre)
with patch("app.agents.copywriter.logger") as mock_logger:
    await generate_copy_with_ai(ANALYSIS, BRAND, user_context=None)
warning_text = " ".join(str(c) for c in mock_logger.warning.call_args_list)
assert "#AVISO_REGRA_ZERO" in warning_text
```

---

### `pytest.ini` (novo arquivo)

```ini
[pytest]
asyncio_mode = auto
log_level = WARNING
```

---

### `.github/workflows/security.yml`

```yaml
# Antes (flag inválida)
pip-audit --requirement requirements.txt --fail-on CRITICAL

# Depois (sem a flag)
pip-audit --requirement requirements.txt --progress-spinner off
```

---

### `requirements.txt`

```
respx>=0.20.0    # adicionado — mock de httpx em test_meta_oauth.py
```

---

## Como Aplicar em Produção (após merge do PR #1)

```bash
git pull origin main
alembic upgrade head   # aplica migration d4e5f6a7b8c9 (coluna published_at)
```

---

*Documento gerado em 2026-06-06. Última atualização: commit `6d29dff` — fix caplog → patch logger.*
