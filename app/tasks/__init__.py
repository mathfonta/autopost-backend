"""
Configuração do Celery — broker Redis, backend Redis.
Workers são iniciados separadamente (ver railway.toml).
"""

from celery import Celery
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "autopost",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[],  # adicionar módulos de tasks aqui conforme criados
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="America/Sao_Paulo",
    enable_utc=True,
    # Evita que tasks fiquem presas indefinidamente
    task_soft_time_limit=300,  # 5 min — warning
    task_time_limit=600,       # 10 min — kill
    # Worker
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    # Beat — usa Redis para armazenar agenda (sem arquivo em disco)
    beat_scheduler="redbeat.RedBeatScheduler",
    redbeat_redis_url=settings.REDIS_URL,
)
