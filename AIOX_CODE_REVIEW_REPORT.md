# Relatório de Code Review — autopost-backend
**Branch:** `claude/code-review-SCPfs`  
**PR:** #1 — "fix: corrige 9 bugs críticos apontados na revisão de código"  
**Data:** 2026-06-06  
**Status CI:** ❌ 1 teste falhando (ver seção "Problema Não Resolvido")

---

## 1. Resumo

Foram identificados e corrigidos 9 bugs críticos no codebase. Adicionalmente, durante o processo de correção do CI, 7 falhas de teste pré-existentes (mascaradas pela parada na primeira falha) foram corrigidas. Resta 1 falha não resolvida descrita na seção final.

---

## 2. Bugs Corrigidos no Código de Produção

### Bug 1 — Race condition TOCTOU em `publish_post` (posts duplicados no Instagram)
**Arquivo:** `app/tasks/pipeline.py`  
**Problema:** A idempotência era feita com read-then-write: `if req.status == published: return`. Dois workers Celery concorrentes podiam ambos passar na verificação antes de qualquer um gravar, causando dois posts no Instagram.  
**Solução:** Substituído por `UPDATE WHERE status NOT IN (published, publishing)` atômico via SQLAlchemy. Apenas o worker que alterar `rowcount > 0` prossegue.

```python
# ANTES — race condition
req_check = _run_sync(_get_request(request_id))
if req_check.status == ContentStatus.published:
    return request_id
_run_sync(_update_status(request_id, ContentStatus.publishing))

# DEPOIS — atômico
if not _run_sync(_try_claim_publishing(request_id)):
    return request_id
```

---

### Bug 2 — `_increment_attack_sequence` executa mesmo sem post_id real
**Arquivo:** `app/tasks/pipeline.py`  
**Problema:** A sequência editorial de ataque era incrementada mesmo quando nem o Instagram nem o Facebook receberam o post (cliente sem credenciais configuradas). O contador driftava sem publicação real.  
**Solução:** Guard `if instagram_post_id or facebook_post_id:` antes do incremento.

---

### Bug 3 — `retry_generate_copy` descartava enrichments
**Arquivo:** `app/tasks/pipeline.py`  
**Problema:** No retry da legenda, `exa_context` e `attack_sequence_position` não eram passados para `generate_copy_with_ai`, zerando os enriquecimentos de tendências e sequência editorial na segunda tentativa.  
**Solução:** Passagem explícita dos campos `exa_context=req.get("exa_trends_context")` e `attack_sequence_position=req.get("attack_sequence_position")`.

---

### Bug 4 — `_get_request_with_client` não retornava `exa_trends_context`
**Arquivo:** `app/tasks/pipeline.py`  
**Problema:** O campo `exa_trends_context` não estava no dicionário retornado por `_get_request_with_client`, então o Bug 3 acima era inevitável mesmo que fosse corrigido na chamada.  
**Solução:** Adicionado `"exa_trends_context": req.exa_trends_context or None` ao dict retornado.

---

### Bug 5 — `published_at` nunca era gravado
**Arquivo:** `app/tasks/pipeline.py` + `app/models/content_request.py` + migration  
**Problema:** A coluna `published_at` não existia no modelo nem no banco. O endpoint de streak (`/insights/streak`) usava `updated_at` que é mutável — qualquer edição posterior à publicação corromperia o contador de dias consecutivos.  
**Solução:**
- Adicionada coluna `published_at` (nullable DateTime) ao modelo.
- `_update_status` seta `published_at = datetime.now(utc)` na primeira transição para `ContentStatus.published` (imutável após set).
- Migration `d4e5f6a7b8c9` com backfill de `updated_at` para posts já publicados.
- `/insights/streak` atualizado para usar `published_at`.

---

### Bug 6 — `/insights` retornava dados do segmento errado (fallback cross-segmento)
**Arquivo:** `app/api/insights.py`  
**Problema:** Quando não havia inteligência de mercado para o segmento do cliente, o endpoint buscava de outros segmentos e retornava dados irrelevantes ao invés de 404.  
**Solução:** Removido o fallback; retorna `HTTP 404` conforme documentado na docstring.

---

### Bug 7 — Regex de hashtag incluía símbolos não-letra (× e ÷)
**Arquivo:** `app/agents/copywriter.py`  
**Problema:** O range Unicode `[À-ú]` incluía os caracteres `×` (U+00D7, multiplicação) e `÷` (U+00F7, divisão), que são símbolos matemáticos, não letras.  
**Solução:** Substituído por `[À-ÖØ-öø-ÿ]` que exclui exatamente esses dois símbolos.

---

### Bug 8 — `user_context` sem limite de tamanho (prompt injection)
**Arquivo:** `app/api/content.py`  
**Problema:** Campo `user_context` no endpoint `POST /content-requests` não tinha validação de tamanho. Payloads gigantes ou tentativas de prompt injection não eram bloqueados na camada de entrada.  
**Solução:** `user_context: str | None = Form(None, max_length=2000)`

---

### Bug 9 — Endpoint de rejeição não gravava mensagem padrão
**Arquivo:** `app/api/content.py`  
**Problema:** `req.error_message = reason or None` — quando o cliente rejeitava sem fornecer motivo, `error_message` ficava `None` no banco.  
**Solução:** `req.error_message = reason or "Rejeitado pelo cliente"`

---

## 3. Falhas de CI Corrigidas (Testes)

### CI Fix 1 — `ModuleNotFoundError: No module named 'respx'`
**Arquivo:** `requirements.txt`  
**Causa:** `tests/test_meta_oauth.py` importava `respx` que não estava em `requirements.txt`.  
**Solução:** Adicionado `respx>=0.20.0`.

---

### CI Fix 2 — `pip-audit --fail-on CRITICAL` flag inválida
**Arquivo:** `.github/workflows/security.yml`  
**Causa:** A flag `--fail-on CRITICAL` não existe na versão do pip-audit instalada; `CRITICAL` era interpretado como argumento posicional conflitando com `-r`.  
**Solução:** Removida a flag inválida; o workflow já falhava corretamente por exit code.

---

### CI Fix 3 — `test_analyst_agent` ConnectError (download HTTP real)
**Arquivo:** `tests/test_analyst_agent.py`  
**Causa:** `analyze_photo_with_ai` faz download HTTP da foto antes de chamar Claude. Os testes mockavam apenas o Claude mas não o httpx, então CI (sem internet) falhava com `ConnectError`.  
**Solução:** Adicionada fixture `autouse` que mocka `httpx.AsyncClient` e `_compress_image_for_claude`.

---

### CI Fix 4 — `test_reject_success` assertion errada
**Arquivo:** `tests/test_approval_api.py`  
**Causa:** Teste esperava `ContentStatus.failed` mas o endpoint retorna corretamente `ContentStatus.rejected`.  
**Solução:** Corrigida a assertion para `ContentStatus.rejected`.

---

### CI Fix 5 — `test_reject_without_reason` — `error_message` era None
**Causa:** Decorrente do Bug 9 acima. O endpoint gravava `None` quando sem motivo. O teste esperava a mensagem padrão.  
**Solução:** Corrigido no endpoint (Bug 9).

---

### CI Fix 6 — `test_no_attack_section_when_sequence_complete[10]`
**Causa:** O code review original indicou que `< 10` era um off-by-one e sugeriu `<= 10`. Isso estava **errado** — `position=10` é o estado "sequência completa, NÃO injetar diretriz" (AC5 da Story 14.2). O guard correto é `0 <= position < 10`.  
**Solução:** Revertido para `< 10`.

---

### CI Fix 7 — `test_r2_key_uses_mp4_extension_for_video` — `r2_mock.called` False
**Arquivo:** `tests/conftest.py`  
**Causa:** O rate limiter `@limiter.limit("10/hour")` usa o IP `"testclient"` para todos os requests do TestClient. Após 10 testes POST em `/content-requests`, o 11º recebia HTTP 429 antes de chegar ao `upload_to_r2`, deixando `r2_mock.called = False`.  
**Solução:** Adicionada fixture `autouse` em `conftest.py` que chama `limiter._storage.reset()` antes de cada teste.

---

## 4. Problema Não Resolvido ❌

### Falha: `test_regra_zero_logs_when_context_missing`
**Arquivo:** `tests/test_copywriter_agent.py:301`  
**Erro:**
```
assert "#AVISO_REGRA_ZERO" in caplog.text
AssertionError: assert '#AVISO_REGRA_ZERO' in ''
where '' = <_pytest.logging.LogCaptureFixture>.text
```

**O que o teste verifica:** Quando `generate_copy_with_ai` é chamada sem `user_context`, o copywriter deve logar `#AVISO_REGRA_ZERO` indicando que campos essenciais de contexto estão ausentes (AC2 da Story 14.1).

**O que foi tentado:**
1. Elevado nível do log de `logger.debug` para `logger.warning` → ainda falha.
2. Adicionado `pytest.ini` com `asyncio_mode = auto` e `log_level = WARNING` → ainda falha.

**Diagnóstico atual:** `caplog.text` retorna string vazia mesmo para `logger.warning`. Isso indica que o handler do `caplog` não está recebendo nenhum record do logger `app.agents.copywriter` durante o teste. O `generate_copy_with_ai` **executa sem erros** (o teste não levanta exceção), o que confirma que a função roda mas os logs não são capturados.

**Suspeita principal:** Incompatibilidade entre `pytest-asyncio >= 0.23` e `caplog` nesta configuração específica. O `caplog` adiciona seu handler no root logger no contexto sync do pytest, mas algo na inicialização da aplicação (imports de FastAPI/Celery/SQLAlchemy na cadeia `from app.agents.copywriter import generate_copy_with_ai`) pode estar configurando o logger `app.agents.copywriter` com `propagate=False` ou com um nível efetivo que impede a emissão, mesmo que pareça funcional.

**Pistas para investigação:**
- Verificar se algum import na cadeia do módulo `app` chama `logging.config.dictConfig()` ou `logging.basicConfig()` com `disable_existing_loggers=True`.
- Verificar se `Celery` ou `SQLAlchemy` reconfiguram o logger `app.*`.
- Testar isoladamente: `python -m pytest tests/test_copywriter_agent.py::test_regra_zero_logs_when_context_missing -xvs` com `--log-cli-level=DEBUG` para ver se o log aparece no output mas não em `caplog`.
- Alternativa de fix: trocar a assertion de `caplog.text` por um mock do `logger.warning` usando `patch("app.agents.copywriter.logger.warning")` e verificar `mock.call_args_list`.

---

## 5. Arquivos Modificados (Resumo)

| Arquivo | Tipo | Descrição |
|---------|------|-----------|
| `app/tasks/pipeline.py` | Produção | Race condition, enrichments no retry, published_at, increment guard |
| `app/agents/copywriter.py` | Produção | Regex Unicode, log level AVISO_REGRA_ZERO |
| `app/api/content.py` | Produção | max_length user_context, mensagem padrão rejeição |
| `app/api/insights.py` | Produção | Remove fallback cross-segmento, streak usa published_at |
| `app/models/content_request.py` | Produção | Coluna published_at |
| `migrations/versions/d4e5f6a7b8c9_*.py` | Migration | Adiciona published_at com backfill |
| `requirements.txt` | Infra | Adiciona respx |
| `.github/workflows/security.yml` | Infra | Remove flag inválida pip-audit |
| `pytest.ini` | Testes | asyncio_mode=auto, log_level=WARNING |
| `tests/conftest.py` | Testes | reset_rate_limiter autouse fixture |
| `tests/test_analyst_agent.py` | Testes | Mock HTTP download foto |
| `tests/test_approval_api.py` | Testes | Corrige assertion ContentStatus.rejected |

---

## 6. Como Aplicar em Produção (após merge)

```bash
git pull origin main
alembic upgrade head   # aplica migration do published_at
```

---

*Documento gerado em 2026-06-06 para revisão pela equipe AIOX.*
