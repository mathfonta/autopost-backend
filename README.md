# AutoPost — Backend

API FastAPI + Workers Celery para a plataforma AutoPost de marketing digital com IA.

---

## Stack

| Camada | Tecnologia |
|--------|-----------|
| API | FastAPI 0.115 + Uvicorn |
| Banco | PostgreSQL via Supabase (asyncpg + SQLAlchemy) |
| Cache / Fila | Redis (Railway add-on) |
| Workers | Celery (worker + beat) |
| IA | Anthropic Claude (Haiku + Sonnet) |
| Storage | Cloudflare R2 (S3-compatible) |
| Deploy | Railway |

---

## Pré-requisitos (local)

- Python 3.12+
- Redis rodando localmente (`redis-server` ou Docker)
- Conta Supabase com projeto criado
- Conta Cloudflare R2 com bucket `autopost-media`

---

## Setup local

### 1. Clonar e criar ambiente virtual

```bash
git clone <repo-url>
cd autopost/backend
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate
```

### 2. Instalar dependências

```bash
pip install -r requirements.txt
```

### 3. Configurar variáveis de ambiente

```bash
cp .env.example .env
```

Edite `.env` e preencha todos os valores (veja a seção **Variáveis de Ambiente** abaixo).

### 4. Rodar a API

```bash
uvicorn app.main:app --reload --port 8000
```

Acesse: http://localhost:8000/health

### 5. Rodar o Worker Celery (terminal separado)

```bash
celery -A app.tasks worker --loglevel=info --concurrency=2
```

### 6. Rodar o Beat/Scheduler (terminal separado)

```bash
celery -A app.tasks beat --loglevel=info
```

---

## Rodar testes

```bash
pip install pytest pytest-anyio httpx
pytest tests/ -v
```

---

## Variáveis de Ambiente

Todas obrigatórias exceto as marcadas como `(opcional)`.

| Variável | Onde encontrar |
|----------|---------------|
| `DATABASE_URL` | Supabase → Settings → Database → Connection string (Transaction mode, porta 5432) |
| `SUPABASE_URL` | Supabase → Settings → API → Project URL |
| `SUPABASE_SERVICE_KEY` | Supabase → Settings → API → service_role key |
| `REDIS_URL` | Railway → Redis → Connect → REDIS_URL |
| `JWT_SECRET` | Gere com: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `JWT_EXPIRE_MINUTES` | Padrão: 60 |
| `CLOUDFLARE_R2_BUCKET` | Cloudflare → R2 → nome do bucket |
| `CLOUDFLARE_R2_ACCESS_KEY` | Cloudflare → R2 → Manage R2 API Tokens |
| `CLOUDFLARE_R2_SECRET_KEY` | idem |
| `CLOUDFLARE_R2_ENDPOINT` | `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` |
| `ANTHROPIC_API_KEY` | console.anthropic.com → API Keys |
| `META_ACCESS_TOKEN` | developers.facebook.com → seu App → Tokens |
| `WHATSAPP_PHONE_NUMBER_ID` | Meta for Developers → WhatsApp → Phone Numbers |
| `WHATSAPP_VERIFY_TOKEN` | Você define (string secreta para validar webhook) |
| `GOOGLE_DRIVE_CLIENT_ID` | (opcional) Google Cloud Console → OAuth 2.0 |
| `DROPBOX_APP_KEY` | (opcional) Dropbox Developers → App Console |
| `ONEDRIVE_CLIENT_ID` | (opcional) Azure Portal → App registrations |

---

## Contas necessárias (checklist de infraestrutura)

Antes do primeiro deploy, crie todas as contas:

- [ ] **Railway** — railway.app → New Project → Deploy from GitHub
  - Adicionar serviços: Web Service (API), Worker (Celery), Scheduler (Beat)
  - Adicionar Redis via Marketplace → Redis

- [ ] **Supabase** — supabase.com → New project `autopost`
  - Anotar: Project URL, service_role key, Database connection string
  - Habilitar Row Level Security nas tabelas (Story 1.3)

- [ ] **Cloudflare R2** — dash.cloudflare.com → R2
  - Criar bucket `autopost-media` (público para leitura)
  - Gerar API Token com permissão Object Read & Write
  - Configurar CORS para permitir upload do frontend

- [ ] **Anthropic** — console.anthropic.com → API Keys
  - Criar chave de API
  - Definir limite de uso mensal para controle de custo

- [ ] **Meta for Developers** — developers.facebook.com
  - Criar App tipo "Business"
  - Habilitar WhatsApp Business API
  - Habilitar Instagram Graph API

---

## Estrutura do projeto

```
backend/
├── app/
│   ├── api/          # Endpoints FastAPI (routers)
│   ├── core/         # Database, Redis, segurança
│   ├── models/       # Modelos SQLAlchemy (Story 1.3)
│   ├── schemas/      # Schemas Pydantic (Story 1.2)
│   ├── tasks/        # Tasks Celery (Story 1.4)
│   ├── agents/       # Agentes IA (Epic 2)
│   ├── config.py     # Settings via env vars
│   └── main.py       # FastAPI app
├── tests/
├── Dockerfile
├── railway.toml
├── requirements.txt
└── .env.example
```

---

## Deploy no Railway

O Railway usa o `Dockerfile` + `railway.toml` automaticamente.
Basta conectar o repositório no Railway e configurar as variáveis de ambiente na UI.

```bash
# Verificar se deploy está OK
curl https://<seu-projeto>.railway.app/health
# Esperado: {"status": "ok", "version": "1.0.0", ...}
```
