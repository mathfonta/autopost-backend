"""
Testes do módulo cerebro: writer, reader e analyzer.
"""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── Fixtures ────────────────────────────────────────────────────

@pytest.fixture
def cerebro_dir(tmp_path):
    """Cria estrutura de cérebro temporária para testes."""
    historico = tmp_path / "historico"
    historico.mkdir()
    (historico / ".gitkeep").touch()
    (tmp_path / "PADROES.md").write_text("", encoding="utf-8")
    (tmp_path / "INSIGHTS.md").write_text("", encoding="utf-8")
    return tmp_path


@pytest.fixture
def req_dict():
    return {
        "id": "test-id-123",
        "analysis_result": {
            "content_type": "obra_realizada",
            "quality": "good",
            "stage": "acabamento",
        },
        "copy_result": {
            "caption": "Obra finalizada com excelência!",
            "cta": "Entre em contato pelo link na bio!",
            "suggested_time": "15:00",
        },
        "design_result": {},
    }


@pytest.fixture
def metrics_dict():
    return {
        "likes": 42,
        "comments": 5,
        "reach": 310,
        "impressions": 450,
        "collected_at": "2026-04-17T15:00:00+00:00",
    }


@pytest.fixture
def historico_with_data(cerebro_dir):
    """Cria arquivo de histórico com dados suficientes para análise."""
    content = """# Histórico — Semana 2026-W17

## Post — 2026-04-17T15:00

- **Tipo:** obra_realizada
- **Qualidade:** good
- **Horário publicado:** 15:00
- **Legenda:** Obra finalizada com excelência!
- **CTA:** Entre em contato pelo link na bio!
- **Curtidas:** 42
- **Comentários:** 5
- **Alcance:** 310
- **Impressões:** 450

---

## Post — 2026-04-16T10:00

- **Tipo:** antes_depois
- **Qualidade:** good
- **Horário publicado:** 10:00
- **Legenda:** Transformação incrível neste projeto!
- **CTA:** Fala com a gente!
- **Curtidas:** 18
- **Comentários:** 2
- **Alcance:** 120
- **Impressões:** 200

---
"""
    (cerebro_dir / "historico" / "2026-W17.md").write_text(content, encoding="utf-8")
    return cerebro_dir


# ─── Writer Tests ────────────────────────────────────────────────

class TestWriter:
    def test_write_post_creates_weekly_file(self, cerebro_dir, req_dict, metrics_dict):
        with patch("app.cerebro.writer.get_cerebro_path", return_value=cerebro_dir):
            from app.cerebro.writer import write_post_to_history
            write_post_to_history(req_dict, metrics_dict)

        historico_files = list((cerebro_dir / "historico").glob("????-W??.md"))
        assert len(historico_files) == 1

    def test_write_post_content(self, cerebro_dir, req_dict, metrics_dict):
        with patch("app.cerebro.writer.get_cerebro_path", return_value=cerebro_dir):
            from app.cerebro.writer import write_post_to_history
            write_post_to_history(req_dict, metrics_dict)

        historico_files = list((cerebro_dir / "historico").glob("????-W??.md"))
        content = historico_files[0].read_text(encoding="utf-8")

        assert "obra_realizada" in content
        assert "42" in content        # likes
        assert "310" in content       # reach
        assert "15:00" in content     # suggested_time

    def test_write_post_appends_multiple_entries(self, cerebro_dir, req_dict, metrics_dict):
        with patch("app.cerebro.writer.get_cerebro_path", return_value=cerebro_dir):
            from app.cerebro.writer import write_post_to_history
            write_post_to_history(req_dict, metrics_dict)
            write_post_to_history(req_dict, metrics_dict)

        historico_files = list((cerebro_dir / "historico").glob("????-W??.md"))
        content = historico_files[0].read_text(encoding="utf-8")
        # Deve ter dois blocos "## Post"
        assert content.count("## Post") == 2

    def test_write_post_never_raises(self, cerebro_dir, req_dict, metrics_dict):
        """Falha no cerebro nunca deve quebrar o pipeline."""
        with patch("app.cerebro.writer.get_cerebro_path", side_effect=Exception("erro simulado")):
            from app.cerebro.writer import write_post_to_history
            # Não deve levantar exceção
            write_post_to_history(req_dict, metrics_dict)

    def test_write_post_empty_results(self, cerebro_dir):
        """Aceita dicts vazios sem erros."""
        with patch("app.cerebro.writer.get_cerebro_path", return_value=cerebro_dir):
            from app.cerebro.writer import write_post_to_history
            write_post_to_history({}, {})

        historico_files = list((cerebro_dir / "historico").glob("????-W??.md"))
        assert len(historico_files) == 1


# ─── Reader Tests ────────────────────────────────────────────────

class TestReader:
    def test_read_patterns_returns_none_when_no_file(self, tmp_path):
        # tmp_path sem PADROES.md — get_cerebro_path aponta para dir sem o arquivo
        with patch("app.cerebro.reader.get_cerebro_path", return_value=tmp_path):
            from app.cerebro.reader import read_patterns
            result = read_patterns()
        assert result is None

    def test_read_patterns_returns_none_when_empty(self, cerebro_dir):
        (cerebro_dir / "PADROES.md").write_text("", encoding="utf-8")
        with patch("app.cerebro.reader.get_cerebro_path", return_value=cerebro_dir):
            from app.cerebro.reader import read_patterns
            result = read_patterns()
        assert result is None

    def test_read_patterns_returns_none_for_template(self, cerebro_dir):
        """Arquivo template sem dados reais retorna None."""
        template = "# Padrões\n\n## Tipo\n*(a descobrir)*\n\n## Horário\n*(a descobrir)*"
        (cerebro_dir / "PADROES.md").write_text(template, encoding="utf-8")
        with patch("app.cerebro.reader.get_cerebro_path", return_value=cerebro_dir):
            from app.cerebro.reader import read_patterns
            result = read_patterns()
        assert result is None

    def test_read_patterns_returns_content_when_valid(self, cerebro_dir):
        """Retorna conteúdo quando gerado pelo Claude (tem marker)."""
        real_content = (
            "<!-- Atualizado automaticamente em 2026-04-21 08:00 UTC pelo Celery Beat -->\n\n"
            "## Tipo de Foto\nObra realizada: média 42 curtidas\n\n"
            "## Horário\n15:00 — melhor desempenho\n"
        )
        (cerebro_dir / "PADROES.md").write_text(real_content, encoding="utf-8")
        with patch("app.cerebro.reader.get_cerebro_path", return_value=cerebro_dir):
            from app.cerebro.reader import read_patterns
            result = read_patterns()
        assert result is not None
        assert "Obra realizada" in result

    def test_read_patterns_never_raises(self):
        """Erro de I/O retorna None, não exceção."""
        with patch("app.cerebro.reader.get_cerebro_path", side_effect=Exception("I/O error")):
            from app.cerebro.reader import read_patterns
            result = read_patterns()
        assert result is None


# ─── Analyzer Tests ──────────────────────────────────────────────

class TestAnalyzer:
    @pytest.mark.asyncio
    async def test_analyze_skips_when_no_historico(self, cerebro_dir):
        with patch("app.cerebro.analyzer.get_cerebro_path", return_value=cerebro_dir):
            from app.cerebro.analyzer import analyze_and_update_patterns
            # Não deve levantar exceção, apenas retornar
            await analyze_and_update_patterns()

        # Arquivos permanecem inalterados (sem dados)
        assert (cerebro_dir / "PADROES.md").read_text() == ""

    @pytest.mark.asyncio
    async def test_analyze_skips_when_historico_too_short(self, cerebro_dir):
        (cerebro_dir / "historico" / "2026-W17.md").write_text("# Header\n\nPouco conteúdo.", encoding="utf-8")
        with patch("app.cerebro.analyzer.get_cerebro_path", return_value=cerebro_dir):
            from app.cerebro.analyzer import analyze_and_update_patterns
            await analyze_and_update_patterns()

        assert (cerebro_dir / "PADROES.md").read_text() == ""

    @pytest.mark.asyncio
    async def test_analyze_updates_files_with_claude_response(self, historico_with_data):
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = json.dumps({
            "padroes": "## Tipo\nObra realizada performa melhor\n\n## Horário\n15:00",
            "insights": "## Total\n2 posts\n\n## Média Curtidas\n30",
        })

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with (
            patch("app.cerebro.analyzer.get_cerebro_path", return_value=historico_with_data),
            patch("app.cerebro.analyzer.anthropic.AsyncAnthropic", return_value=mock_client),
        ):
            from app.cerebro.analyzer import analyze_and_update_patterns
            await analyze_and_update_patterns()

        padroes = (historico_with_data / "PADROES.md").read_text(encoding="utf-8")
        insights = (historico_with_data / "INSIGHTS.md").read_text(encoding="utf-8")

        assert "Obra realizada" in padroes
        assert "15:00" in padroes
        assert "2 posts" in insights
        assert "Atualizado automaticamente" in padroes

    @pytest.mark.asyncio
    async def test_analyze_raises_on_invalid_json(self, historico_with_data):
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = "isso não é json"

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with (
            patch("app.cerebro.analyzer.get_cerebro_path", return_value=historico_with_data),
            patch("app.cerebro.analyzer.anthropic.AsyncAnthropic", return_value=mock_client),
        ):
            from app.cerebro.analyzer import analyze_and_update_patterns
            with pytest.raises(ValueError, match="JSON inválido"):
                await analyze_and_update_patterns()
