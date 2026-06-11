"""Testes do pipeline autônomo — Story 17.2."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestThemeGenerator:
    """Testa generate_slide_structure."""

    @pytest.mark.asyncio
    async def test_tema_valido_retorna_estrutura(self):
        """Tema existente deve retornar estrutura com campos obrigatórios."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='''
        {
          "title_card": {"headline": "5 erros que encarecem sua reforma", "subheadline": "Você comete algum deles?"},
          "content_slides": [
            {"number": 1, "headline": "Erro #1", "body": "Não fazer orçamentos comparativos antes de contratar."},
            {"number": 2, "headline": "Erro #2", "body": "Comprar materiais sem calcular a metragem correta."}
          ],
          "cta_card": {"headline": "Evite esses erros", "body": "Me chama para um orçamento sem compromisso."}
        }
        ''')]

        with patch("app.agents.theme_generator._client") as mock_client:
            mock_client.messages.create.return_value = mock_response
            from app.agents.theme_generator import generate_slide_structure

            structure = await generate_slide_structure(
                theme_id="cc_erros_reforma",
                brand_profile={"company_name": "Construtora Silva", "segment": "construção civil"},
            )

        assert "title_card" in structure
        assert "content_slides" in structure
        assert "cta_card" in structure
        assert len(structure["content_slides"]) >= 1

    @pytest.mark.asyncio
    async def test_tema_invalido_levanta_valor_error(self):
        from app.agents.theme_generator import generate_slide_structure
        with pytest.raises(ValueError, match="não encontrado"):
            await generate_slide_structure(
                theme_id="tema_inexistente_xyz",
                brand_profile={},
            )


class TestSlideDesigner:
    """Testa render_carousel_slides."""

    @pytest.mark.asyncio
    async def test_renderiza_slides_retorna_bytes(self):
        from app.agents.slide_designer import render_carousel_slides

        structure = {
            "title_card": {"headline": "5 erros na reforma", "subheadline": "Evite-os"},
            "content_slides": [
                {"number": 1, "headline": "Erro #1", "body": "Descrição do erro um."},
                {"number": 2, "headline": "Erro #2", "body": "Descrição do erro dois."},
            ],
            "cta_card": {"headline": "Fale conosco", "body": "Orçamento grátis."},
        }
        brand_profile = {"company_name": "Construtora", "primary_color": "#2354E8"}

        slides = await render_carousel_slides(structure, brand_profile)

        assert len(slides) == 4  # título + 2 conteúdo + CTA
        for i, slide in enumerate(slides):
            assert isinstance(slide, bytes), f"slide {i} não é bytes"
            assert len(slide) > 1000, f"slide {i} muito pequeno ({len(slide)} bytes)"

    @pytest.mark.asyncio
    async def test_cor_invalida_usa_default(self):
        from app.agents.slide_designer import render_carousel_slides

        structure = {
            "title_card": {"headline": "Título", "subheadline": None},
            "content_slides": [{"number": 1, "headline": "Slide 1", "body": "Corpo"}],
            "cta_card": {"headline": "CTA", "body": "Ação"},
        }
        # Cor inválida — deve usar default sem levantar exceção
        slides = await render_carousel_slides(structure, {"primary_color": "não-é-hex"})
        assert len(slides) == 3
