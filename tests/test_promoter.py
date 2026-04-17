"""
Testes do módulo cerebro.promoter — Motor de Promoção Local → Global.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── Fixtures ────────────────────────────────────────────────────

@pytest.fixture
def local_cerebro(tmp_path):
    """Cérebro local com dados suficientes para promoção."""
    local = tmp_path / "local"
    local.mkdir()

    (local / "PADROES.md").write_text(
        "<!-- Atualizado automaticamente em 2026-04-21 08:00 UTC pelo Celery Beat -->\n\n"
        "## Tipo de Foto\nObra realizada: média 42 curtidas\n\n"
        "## Melhor Horário\n15:00 às terças e quintas\n\n"
        "## CTA Mais Eficaz\n'Entre em contato pelo WhatsApp' — 3× mais cliques\n",
        encoding="utf-8",
    )
    (local / "INSIGHTS.md").write_text(
        "<!-- Atualizado automaticamente em 2026-04-21 -->\n\n"
        "## Total de Posts\n8 posts\n\n"
        "## Média de Curtidas\n38\n\n"
        "## Média de Alcance\n290\n",
        encoding="utf-8",
    )
    return local


@pytest.fixture
def global_cerebro(tmp_path):
    """Cérebro global vazio (estrutura mínima criada pelo promoter)."""
    return tmp_path / "global"


@pytest.fixture
def global_cerebro_with_data(tmp_path):
    """Cérebro global já com conteúdo existente."""
    global_path = tmp_path / "global"
    (global_path / "projetos").mkdir(parents=True)
    (global_path / "PADROES_GLOBAIS.md").write_text(
        "# Padrões Globais\n\n## Universal\n\n- Fotos com boa iluminação performam melhor *(confiança: 90%)*\n",
        encoding="utf-8",
    )
    (global_path / "APRENDIZADOS.md").write_text(
        "# Aprendizados\n\n",
        encoding="utf-8",
    )
    (global_path / "projetos" / "autopost.md").write_text(
        "# Projeto: autopost\n\n",
        encoding="utf-8",
    )
    return global_path


@pytest.fixture
def mock_claude_response():
    """Resposta padrão do Claude para classificação."""
    return {
        "patterns": [
            {"pattern": "Horário 15:00 gera mais engajamento em dias úteis", "type": "universal", "confidence": 0.85},
            {"pattern": "Fotos de obra finalizada superam antes/depois em construção civil", "type": "nicho", "confidence": 0.80},
            {"pattern": "Cliente X prefere tom formal", "type": "local", "confidence": 0.90},
        ],
        "monthly_summary": "8 posts publicados. Média de 38 curtidas e 290 de alcance. Padrão principal: horário 15:00 e fotos de obra finalizada.",
        "technical_lessons": [],
    }


def _make_mock_client(response_dict: dict) -> MagicMock:
    mock_response = MagicMock()
    mock_response.content = [MagicMock()]
    mock_response.content[0].text = json.dumps(response_dict)

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    return mock_client


# ─── Tests ───────────────────────────────────────────────────────

class TestPromoter:
    @pytest.mark.asyncio
    async def test_promote_skips_when_local_content_too_short(self, global_cerebro):
        """Não promove quando conteúdo local é insuficiente."""
        empty_local = global_cerebro.parent / "empty_local"
        empty_local.mkdir()
        (empty_local / "PADROES.md").write_text("# Padrões\n*(a descobrir)*", encoding="utf-8")

        with patch("app.cerebro.promoter.get_cerebro_path", return_value=empty_local), \
             patch("app.cerebro.promoter.get_global_cerebro_path", return_value=global_cerebro):
            from app.cerebro.promoter import promote_to_global
            await promote_to_global()

        # Global não foi criado (nada a promover)
        assert not global_cerebro.exists()

    @pytest.mark.asyncio
    async def test_promote_creates_global_structure_if_missing(self, local_cerebro, global_cerebro, mock_claude_response):
        """Cria estrutura global se não existir."""
        mock_client = _make_mock_client(mock_claude_response)

        with patch("app.cerebro.promoter.get_cerebro_path", return_value=local_cerebro), \
             patch("app.cerebro.promoter.get_global_cerebro_path", return_value=global_cerebro), \
             patch("app.cerebro.promoter.anthropic.AsyncAnthropic", return_value=mock_client):
            from app.cerebro.promoter import promote_to_global
            await promote_to_global()

        assert (global_cerebro / "PADROES_GLOBAIS.md").exists()
        assert (global_cerebro / "APRENDIZADOS.md").exists()
        assert (global_cerebro / "projetos").is_dir()

    @pytest.mark.asyncio
    async def test_promote_adds_universal_patterns(self, local_cerebro, global_cerebro, mock_claude_response):
        """Padrões universal são adicionados ao PADROES_GLOBAIS.md."""
        mock_client = _make_mock_client(mock_claude_response)

        with patch("app.cerebro.promoter.get_cerebro_path", return_value=local_cerebro), \
             patch("app.cerebro.promoter.get_global_cerebro_path", return_value=global_cerebro), \
             patch("app.cerebro.promoter.anthropic.AsyncAnthropic", return_value=mock_client):
            from app.cerebro.promoter import promote_to_global
            await promote_to_global()

        content = (global_cerebro / "PADROES_GLOBAIS.md").read_text(encoding="utf-8")
        assert "15:00 gera mais engajamento" in content

    @pytest.mark.asyncio
    async def test_promote_adds_nicho_patterns(self, local_cerebro, global_cerebro, mock_claude_response):
        """Padrões nicho são adicionados com seção do segmento."""
        mock_client = _make_mock_client(mock_claude_response)

        with patch("app.cerebro.promoter.get_cerebro_path", return_value=local_cerebro), \
             patch("app.cerebro.promoter.get_global_cerebro_path", return_value=global_cerebro), \
             patch("app.cerebro.promoter.anthropic.AsyncAnthropic", return_value=mock_client):
            from app.cerebro.promoter import promote_to_global
            await promote_to_global(segment="construção civil")

        content = (global_cerebro / "PADROES_GLOBAIS.md").read_text(encoding="utf-8")
        assert "obra finalizada superam antes/depois" in content

    @pytest.mark.asyncio
    async def test_promote_skips_local_patterns(self, local_cerebro, global_cerebro, mock_claude_response):
        """Padrões local NÃO são adicionados ao global."""
        mock_client = _make_mock_client(mock_claude_response)

        with patch("app.cerebro.promoter.get_cerebro_path", return_value=local_cerebro), \
             patch("app.cerebro.promoter.get_global_cerebro_path", return_value=global_cerebro), \
             patch("app.cerebro.promoter.anthropic.AsyncAnthropic", return_value=mock_client):
            from app.cerebro.promoter import promote_to_global
            await promote_to_global()

        content = (global_cerebro / "PADROES_GLOBAIS.md").read_text(encoding="utf-8")
        assert "Cliente X prefere tom formal" not in content

    @pytest.mark.asyncio
    async def test_promote_updates_monthly_summary(self, local_cerebro, global_cerebro_with_data, mock_claude_response):
        """Sumário mensal é adicionado ao projetos/autopost.md."""
        mock_client = _make_mock_client(mock_claude_response)

        with patch("app.cerebro.promoter.get_cerebro_path", return_value=local_cerebro), \
             patch("app.cerebro.promoter.get_global_cerebro_path", return_value=global_cerebro_with_data), \
             patch("app.cerebro.promoter.anthropic.AsyncAnthropic", return_value=mock_client):
            from app.cerebro.promoter import promote_to_global
            await promote_to_global()

        content = (global_cerebro_with_data / "projetos" / "autopost.md").read_text(encoding="utf-8")
        assert "8 posts publicados" in content

    @pytest.mark.asyncio
    async def test_promote_writes_technical_lessons(self, local_cerebro, global_cerebro_with_data):
        """Lições técnicas são escritas em APRENDIZADOS.md."""
        response_with_lessons = {
            "patterns": [{"pattern": "teste", "type": "universal", "confidence": 0.8}],
            "monthly_summary": "Mês normal.",
            "technical_lessons": ["Timeout de 30s no Claude é suficiente para copy"],
        }
        mock_client = _make_mock_client(response_with_lessons)

        with patch("app.cerebro.promoter.get_cerebro_path", return_value=local_cerebro), \
             patch("app.cerebro.promoter.get_global_cerebro_path", return_value=global_cerebro_with_data), \
             patch("app.cerebro.promoter.anthropic.AsyncAnthropic", return_value=mock_client):
            from app.cerebro.promoter import promote_to_global
            await promote_to_global()

        content = (global_cerebro_with_data / "APRENDIZADOS.md").read_text(encoding="utf-8")
        assert "Timeout de 30s" in content

    @pytest.mark.asyncio
    async def test_promote_no_duplicate_patterns(self, local_cerebro, global_cerebro_with_data, mock_claude_response):
        """Padrões idênticos não são duplicados no global."""
        # Adiciona o padrão exato que o mock vai retornar
        existing = (global_cerebro_with_data / "PADROES_GLOBAIS.md").read_text(encoding="utf-8")
        line = "- Horário 15:00 gera mais engajamento em dias úteis *(confiança: 85%)*"
        (global_cerebro_with_data / "PADROES_GLOBAIS.md").write_text(
            existing + f"\n{line}\n", encoding="utf-8"
        )

        mock_client = _make_mock_client(mock_claude_response)

        with patch("app.cerebro.promoter.get_cerebro_path", return_value=local_cerebro), \
             patch("app.cerebro.promoter.get_global_cerebro_path", return_value=global_cerebro_with_data), \
             patch("app.cerebro.promoter.anthropic.AsyncAnthropic", return_value=mock_client):
            from app.cerebro.promoter import promote_to_global
            await promote_to_global()

        content = (global_cerebro_with_data / "PADROES_GLOBAIS.md").read_text(encoding="utf-8")
        assert content.count("15:00 gera mais engajamento") == 1

    @pytest.mark.asyncio
    async def test_promote_raises_on_invalid_json(self, local_cerebro, global_cerebro):
        """ValueError quando Claude retorna JSON inválido."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = "isso não é json"

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("app.cerebro.promoter.get_cerebro_path", return_value=local_cerebro), \
             patch("app.cerebro.promoter.get_global_cerebro_path", return_value=global_cerebro), \
             patch("app.cerebro.promoter.anthropic.AsyncAnthropic", return_value=mock_client):
            from app.cerebro.promoter import promote_to_global
            with pytest.raises(ValueError, match="JSON inválido"):
                await promote_to_global()
