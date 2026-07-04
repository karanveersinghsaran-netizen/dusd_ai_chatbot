"""Shared test doubles for app/store tests."""


class FakeRedisClient:
    """Minimal dict-backed stand-in for redis.Redis, covering the subset of the
    API RedisStore uses (get/setex/exists/delete). TTLs are accepted but not enforced."""

    def __init__(self):
        self._data: dict = {}

    def get(self, key):
        return self._data.get(key)

    def setex(self, key, ttl, value):
        self._data[key] = value

    def exists(self, *keys):
        return sum(1 for k in keys if k in self._data)

    def delete(self, *keys):
        count = 0
        for k in keys:
            if k in self._data:
                del self._data[k]
                count += 1
        return count
