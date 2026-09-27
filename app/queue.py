import logging
from collections.abc import Sequence

from redis import Redis, RedisError

from app.config import settings
from app.db import Job

log = logging.getLogger(__name__)
redis = Redis.from_url(
    settings.redis_url, decode_responses=True, socket_connect_timeout=1, socket_timeout=1
)


def publish(jobs: Sequence[Job]) -> bool:
    """Redis is a disposable ready index; PostgreSQL reconciliation repairs loss."""
    try:
        if jobs:
            redis.zadd(settings.queue_key, {j.id: j.priority for j in jobs})
        return True
    except RedisError:
        log.warning("redis_publish_unavailable")
        return False


def pop() -> str | None:
    result = redis.zpopmin(settings.queue_key)
    return result[0][0] if result else None
