"""
Escreve resultados de posts no histórico semanal do cérebro local.
"""
import logging
from datetime import datetime, timezone

from app.cerebro.reader import get_cerebro_path

logger = logging.getLogger(__name__)


def write_post_to_history(req: dict, metrics: dict) -> None:
    """
    Escreve entrada do post no arquivo semanal do histórico.
    Usa append — nunca sobrescreve dados existentes.

    Args:
        req:     dict com analysis_result, copy_result, design_result
        metrics: dict com likes, comments, reach, impressions, collected_at
    """
    try:
        cerebro_path = get_cerebro_path()
        historico_dir = cerebro_path / "historico"
        historico_dir.mkdir(parents=True, exist_ok=True)

        # Arquivo da semana atual: YYYY-WNN.md
        now = datetime.now(timezone.utc)
        year, week, _ = now.isocalendar()
        filename = historico_dir / f"{year}-W{week:02d}.md"

        analysis = req.get("analysis_result") or {}
        copy = req.get("copy_result") or {}

        content_type = analysis.get("content_type", "desconhecido")
        quality = analysis.get("quality", "desconhecido")
        stage = analysis.get("stage", "")

        caption_raw = copy.get("caption", "")
        caption = (caption_raw[:100] + "...") if len(caption_raw) > 100 else caption_raw
        suggested_time = copy.get("suggested_time", "não informado")
        cta = copy.get("cta", "")

        published_at = (metrics.get("collected_at") or now.isoformat())[:16]
        likes = metrics.get("likes", 0)
        comments = metrics.get("comments", 0)
        reach = metrics.get("reach", 0)
        impressions = metrics.get("impressions", 0)

        entry_lines = [
            f"\n## Post — {published_at}\n",
            f"- **Tipo:** {content_type}",
        ]
        if stage:
            entry_lines.append(f"- **Etapa:** {stage}")
        entry_lines += [
            f"- **Qualidade:** {quality}",
            f"- **Horário publicado:** {suggested_time}",
            f"- **Legenda:** {caption}",
        ]
        if cta:
            entry_lines.append(f"- **CTA:** {cta}")
        entry_lines += [
            f"- **Curtidas:** {likes}",
            f"- **Comentários:** {comments}",
            f"- **Alcance:** {reach}",
            f"- **Impressões:** {impressions}",
            "\n---",
        ]
        entry = "\n".join(entry_lines) + "\n"

        # Cria arquivo com header se ainda não existe
        if not filename.exists():
            header = f"# Histórico — Semana {year}-W{week:02d}\n\n"
            filename.write_text(header, encoding="utf-8")

        with open(filename, "a", encoding="utf-8") as f:
            f.write(entry)

        logger.info(f"[cerebro.writer] post salvo → {filename.name} (likes={likes} reach={reach})")

    except Exception as exc:
        # Falha no cerebro NUNCA deve quebrar o pipeline principal
        logger.warning(f"[cerebro.writer] falha ao escrever no cérebro: {exc}")
