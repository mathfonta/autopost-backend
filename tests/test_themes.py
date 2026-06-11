"""Testes unitários para GET /insights/themes."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.api.insights import _normalize_segment
from app.data.theme_library import THEME_LIBRARY


class TestNormalizeSegment:
    def test_lowercase(self):
        assert _normalize_segment("Construção Civil") == "construcao civil"

    def test_remove_accents(self):
        assert _normalize_segment("saúde") == "saude"

    def test_strip_whitespace(self):
        assert _normalize_segment("  advocacia  ") == "advocacia"

    def test_empty_string(self):
        assert _normalize_segment("") == ""


class TestThemeLibrary:
    def test_has_default_key(self):
        assert "default" in THEME_LIBRARY

    def test_default_has_themes(self):
        assert len(THEME_LIBRARY["default"]) >= 2

    def test_construcao_civil_has_themes(self):
        assert "construção civil" in THEME_LIBRARY
        assert len(THEME_LIBRARY["construção civil"]) >= 3

    def test_theme_has_required_fields(self):
        for segment, themes in THEME_LIBRARY.items():
            for theme in themes:
                assert "id" in theme, f"Theme {theme} missing 'id'"
                assert "title" in theme
                assert "description" in theme
                assert "objective" in theme
                assert "slide_count" in theme
                assert "tags" in theme

    def test_total_themes_count(self):
        total = sum(len(v) for k, v in THEME_LIBRARY.items() if k != "default")
        assert total >= 10, f"Expected >= 10 non-default themes, got {total}"
