"""
Unit Tests for Redis Student Planned Courses Session Cache.
Verifies plan persistence across simulated page reload and automatic expiration on inactivity.
"""

from src.stores.redis_client import RedisClient


def test_redis_session_lifecycle():
    redis_client = RedisClient(use_mock=True)
    redis_client.connect()

    # Run lifecycle test with 2-second TTL
    test_result = redis_client.test_session_lifecycle(student_id=77, course_ids=[101, 102, 103])

    assert test_result["survived_reload"] is True
    assert test_result["reload_plan"] == [101, 102, 103]
    assert test_result["expired_after_inactivity"] is True
    assert test_result["status"] == "PASS"


def test_redis_session_invalidation():
    redis_client = RedisClient(use_mock=True)
    redis_client.connect()

    redis_client.save_planned_courses(student_id=88, course_ids=[201, 202])
    assert redis_client.get_planned_courses(student_id=88) is not None

    redis_client.invalidate_session(student_id=88)
    assert redis_client.get_planned_courses(student_id=88) is None


import unittest


class TestRedisSession(unittest.TestCase):
    def test_lifecycle(self):
        test_redis_session_lifecycle()

    def test_invalidation(self):
        test_redis_session_invalidation()
