"""
Testes para app/core/video.py — compress_video().

Casos cobertos:
  1. Vídeo pequeno (<= 50 MB) → sem compressão, sem chamar FFmpeg
  2. Vídeo grande (> 50 MB)   → FFmpeg comprime, retorna bytes menores
  3. FFmpeg indisponível      → fallback gracioso para original
  4. FFmpeg retorna erro      → fallback gracioso para original
  5. FFmpeg timeout           → fallback gracioso para original
"""

import subprocess
from unittest.mock import patch

from app.core.video import MAX_COMPRESSED_BYTES, compress_video


def _make_bytes(mb: float) -> bytes:
    return b"\x00" * int(mb * 1024 * 1024)


class TestCompressVideo:

    def test_small_video_skips_compression(self):
        """Vídeo <= 50 MB é retornado sem alteração e sem chamar FFmpeg."""
        small = _make_bytes(10)
        with patch("app.core.video.subprocess.run") as mock_run:
            result = compress_video(small)
        assert result is small
        mock_run.assert_not_called()

    def test_boundary_at_limit_skips_compression(self):
        """Vídeo exatamente em MAX_COMPRESSED_BYTES não é comprimido."""
        at_limit = b"\x00" * MAX_COMPRESSED_BYTES
        with patch("app.core.video.subprocess.run") as mock_run:
            result = compress_video(at_limit)
        assert result is at_limit
        mock_run.assert_not_called()

    def test_large_video_is_compressed(self):
        """Vídeo > 50 MB passa pelo FFmpeg e retorna bytes do arquivo comprimido."""
        large = _make_bytes(60)
        compressed_data = _make_bytes(5)

        def _fake_ffmpeg(cmd, capture_output, timeout):
            output_path = cmd[-1]
            with open(output_path, "wb") as f:
                f.write(compressed_data)
            return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"", stderr=b"")

        with patch("app.core.video.subprocess.run", side_effect=_fake_ffmpeg):
            result = compress_video(large)

        assert result == compressed_data
        assert len(result) < len(large)

    def test_ffmpeg_unavailable_returns_original(self):
        """FileNotFoundError (FFmpeg não instalado) → fallback para original."""
        large = _make_bytes(80)
        with patch("app.core.video.subprocess.run", side_effect=FileNotFoundError("ffmpeg not found")):
            result = compress_video(large)
        assert result is large

    def test_ffmpeg_nonzero_returncode_returns_original(self):
        """FFmpeg com returncode != 0 → fallback para original."""
        large = _make_bytes(60)

        def _failed(cmd, capture_output, timeout):
            return subprocess.CompletedProcess(cmd, returncode=1, stdout=b"", stderr=b"error")

        with patch("app.core.video.subprocess.run", side_effect=_failed):
            result = compress_video(large)
        assert result is large

    def test_ffmpeg_timeout_returns_original(self):
        """TimeoutExpired → fallback para original."""
        large = _make_bytes(60)
        with patch("app.core.video.subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 60)):
            result = compress_video(large)
        assert result is large

    def test_quicktime_content_type_small_skips_compression(self):
        """MOV (video/quicktime) pequeno é retornado sem compressão."""
        small = _make_bytes(10)
        with patch("app.core.video.subprocess.run") as mock_run:
            result = compress_video(small, content_type="video/quicktime")
        assert result is small
        mock_run.assert_not_called()
