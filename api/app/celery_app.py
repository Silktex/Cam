"""
Celery application configuration for background post-processing tasks.
"""
from celery import Celery
from app.config import settings

celery_app = Celery(
    "camera_system",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.autodiscover_tasks(["app.tasks"])
