"""Shared test doubles for app/store tests."""


class FakeRedisClient:
    """Minimal dict-backed stand-in for redis.Redis, covering the subset of the
    API RedisStore uses (get/setex/incr/expire/ttl/exists/delete). TTLs are
    recorded (for assertions) but not actually enforced/expired."""

    def __init__(self):
        self._data: dict = {}
        self._ttls: dict = {}

    def get(self, key):
        return self._data.get(key)

    def setex(self, key, ttl, value):
        self._data[key] = value
        self._ttls[key] = ttl

    def incr(self, key):
        self._data[key] = str(int(self._data.get(key, 0)) + 1)
        return int(self._data[key])

    def expire(self, key, ttl):
        if key not in self._data:
            return False
        self._ttls[key] = ttl
        return True

    def ttl(self, key):
        if key not in self._data:
            return -2
        return self._ttls.get(key, -1)

    def exists(self, *keys):
        return sum(1 for k in keys if k in self._data)

    def delete(self, *keys):
        count = 0
        for k in keys:
            if k in self._data:
                del self._data[k]
                self._ttls.pop(k, None)
                count += 1
        return count
