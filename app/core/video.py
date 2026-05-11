"""
Utilitários de vídeo — compressão antes do armazenamento no R2.
"""
import logging
import os
import subprocess
import tempfile

logger = logging.getLogger(__name__)

MAX_COMPRESSED_BYTES = 50 * 1024 * 1024   # 50 MB — target de compressão
MAX_FALLBACK_BYTES   = 200 * 1024 * 1024  # 200 MB — aceita sem compressão se FFmpeg falhar


def compress_video(video_bytes: bytes, content_type: str = "video/mp4") -> bytes:
    """
    Comprime vídeo com FFmpeg (CRF 28, H.264 + AAC, max 1080px de largura).

    - Vídeos <= 50 MB: retorna original sem processar.
    - Fallback gracioso: se FFmpeg falhar ou der timeout, retorna original.

    Returns:
        bytes do vídeo comprimido (ou original em caso de fallback).
    """
    original_mb = len(video_bytes) / (1024 * 1024)

    if len(video_bytes) <= MAX_COMPRESSED_BYTES:
        logger.info(f"[video] sem compressão necessária ({original_mb:.1f}MB <= 50MB)")
        return video_bytes

    logger.info(f"[video] iniciando compressão ({original_mb:.1f}MB)")

    try:
        ext = ".mov" if content_type == "video/quicktime" else ".mp4"

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path  = os.path.join(tmpdir, f"input{ext}")
            output_path = os.path.join(tmpdir, "output.mp4")

            with open(input_path, "wb") as f:
                f.write(video_bytes)

            cmd = [
                "ffmpeg", "-y",
                "-i", input_path,
                "-vcodec", "libx264",
                "-crf", "28",
                "-preset", "fast",
                "-vf", "scale=min(iw\\,1080):-2",  # cap 1080px largura, aspect ratio preservado
                "-acodec", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                output_path,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=60,
            )

            if result.returncode != 0 or not os.path.exists(output_path):
                logger.warning(
                    f"[video] FFmpeg falhou (rc={result.returncode}), usando original. "
                    f"stderr: {result.stderr[-200:].decode('utf-8', errors='replace')}"
                )
                return video_bytes

            with open(output_path, "rb") as f:
                compressed = f.read()

        compressed_mb = len(compressed) / (1024 * 1024)
        logger.info(f"[video] compressão OK: {original_mb:.1f}MB → {compressed_mb:.1f}MB")
        return compressed

    except subprocess.TimeoutExpired:
        logger.warning("[video] FFmpeg timeout (60s), usando original")
        return video_bytes
    except Exception as exc:
        logger.warning(f"[video] erro na compressão: {exc}, usando original")
        return video_bytes
