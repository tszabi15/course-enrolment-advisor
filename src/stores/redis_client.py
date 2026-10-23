"""
Redis Store Client for Course Enrolment Advisor.
Derived Key-Value cache for student planned course sessions with TTL.
Demonstrates session persistence across page reload and automatic expiration on inactivity.
"""

import time
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from config import config

logger = logging.getLogger(__name__)


class RedisClient:
    def __init__(self, host: Optional[str] = None, port: Optional[int] = None, password: Optional[str] = None, use_mock: bool = False):
        self.host = host or config.redis.host
        self.port = port or config.redis.port
        self.password = password or config.redis.password
        self.use_mock = use_mock
        self._client = None
        self._is_connected = False
        self._mock_kv: Dict[str, Tuple[str, float]] = {}  # key -> (value, expiry_timestamp)

    def connect(self):
        if self.use_mock:
            self._is_connected = False
            return
        try:
            import redis
            self._client = redis.Redis(
                host=self.host,
                port=self.port,
                password=self.password,
                decode_responses=True,
                socket_timeout=2.0
            )
            self._client.ping()
            self._is_connected = True
            logger.info("Successfully connected to Redis server.")
        except Exception as e:
            logger.warning(f"Redis live connection unavailable ({e}). Using in-memory fallback simulation.")
            self._is_connected = False

    def _session_key(self, student_id: int) -> str:
        return f"student:{student_id}:planned_courses"

    def save_planned_courses(self, student_id: int, course_ids: List[int], ttl_seconds: Optional[int] = None) -> Dict[str, Any]:
        """
        Save student's planned courses into session cache with TTL and provenance metadata.
        """
        ttl = ttl_seconds if ttl_seconds is not None else config.redis.session_ttl
        payload = {
            "student_id": student_id,
            "planned_course_ids": course_ids,
            "source_id": f"student_session:{student_id}",
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
            "ttl_seconds": ttl
        }
        val_str = json.dumps(payload)
        key = self._session_key(student_id)

        if self._is_connected:
            self._client.setex(key, ttl, val_str)
        else:
            expiry = time.time() + ttl
            self._mock_kv[key] = (val_str, expiry)

        return payload

    def get_planned_courses(self, student_id: int) -> Optional[Dict[str, Any]]:
        """
        Retrieve student's planned courses from cache. Returns None if expired or not set.
        """
        key = self._session_key(student_id)
        if self._is_connected:
            raw = self._client.get(key)
            if raw:
                return json.loads(raw)
            return None
        else:
            if key in self._mock_kv:
                val_str, expiry = self._mock_kv[key]
                if time.time() < expiry:
                    return json.loads(val_str)
                else:
                    del self._mock_kv[key]
            return None

    def invalidate_session(self, student_id: int):
        key = self._session_key(student_id)
        if self._is_connected:
            self._client.delete(key)
        else:
            self._mock_kv.pop(key, None)

    def test_session_lifecycle(self, student_id: int, course_ids: List[int]) -> Dict[str, Any]:
        """
        Required Query / Workflow:
        Demonstrates that the plan survives a page reload simulation
        and expires after inactivity.
        """
        # 1. Store session with a short 2-second TTL for testing
        saved = self.save_planned_courses(student_id, course_ids, ttl_seconds=2)

        # 2. Simulate page reload immediately
        reload_read = self.get_planned_courses(student_id)
        survived = (reload_read is not None and reload_read["planned_course_ids"] == course_ids)

        # 3. Simulate inactivity by sleeping beyond TTL
        time.sleep(2.2)
        after_inactivity_read = self.get_planned_courses(student_id)
        expired = (after_inactivity_read is None)

        return {
            "student_id": student_id,
            "initial_plan": course_ids,
            "survived_reload": survived,
            "reload_plan": reload_read["planned_course_ids"] if reload_read else None,
            "expired_after_inactivity": expired,
            "status": "PASS" if (survived and expired) else "FAIL"
        }

    def close(self):
        if self._client:
            self._client.close()
            self._client = None
            self._is_connected = False
