"""
Cliente Cloudflare R2 — compatível com S3 via boto3.
Upload assíncrono via executor para não bloquear o event loop.
"""

import asyncio
import logging
from functools import partial

import boto3
from botocore.client import Config

from app.config import get_settings

logger = logging.getLogger(__name__)


def _get_r2_client():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.CLOUDFLARE_R2_ENDPOINT,
        aws_access_key_id=settings.CLOUDFLARE_R2_ACCESS_KEY,
        aws_secret_access_key=settings.CLOUDFLARE_R2_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def _sync_upload(key: str, data: bytes, content_type: str) -> str:
    """Upload síncrono para R2. Chamado via executor."""
    settings = get_settings()
    client = _get_r2_client()
    client.put_object(
        Bucket=settings.CLOUDFLARE_R2_BUCKET,
        Key=key,
        Body=data,
        ContentType=content_type,
    )
    # URL pública: usa CLOUDFLARE_R2_PUBLIC_URL se configurado, senão endpoint/bucket
    public_base = settings.CLOUDFLARE_R2_PUBLIC_URL.rstrip("/")
    if not public_base:
        public_base = f"{settings.CLOUDFLARE_R2_ENDPOINT.rstrip('/')}/{settings.CLOUDFLARE_R2_BUCKET}"
    return f"{public_base}/{key}"


async def upload_to_r2(key: str, data: bytes, content_type: str = "image/jpeg") -> str:
    """Upload bytes para Cloudflare R2. Retorna a URL pública do objeto."""
    loop = asyncio.get_event_loop()
    url = await loop.run_in_executor(None, partial(_sync_upload, key, data, content_type))
    logger.info(f"[storage] upload key={key} size={len(data) // 1024}KB")
    return url
