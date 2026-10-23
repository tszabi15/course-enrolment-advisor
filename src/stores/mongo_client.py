"""
MongoDB Store Client for Course Enrolment Advisor.
System of Record for rich, semi-structured course descriptions, syllabi, reading lists,
and component requirements (labs, projects, exams).
"""

import logging
from typing import List, Dict, Any, Optional
from config import config

logger = logging.getLogger(__name__)


class MongoClient:
    def __init__(self, uri: Optional[str] = None, db_name: Optional[str] = None, use_mock: bool = False):
        self.uri = uri or config.mongo.uri
        self.db_name = db_name or config.mongo.db
        self.use_mock = use_mock
        self._client = None
        self._db = None
        self._is_connected = False
        self._mock_collection = []

    def connect(self):
        if self.use_mock:
            self._is_connected = False
            return
        try:
            from pymongo import MongoClient as PyMongoClient
            self._client = PyMongoClient(self.uri, serverSelectionTimeoutMS=2500)
            # Force server roundtrip to verify connection
            self._client.admin.command('ping')
            self._db = self._client[self.db_name]
            self._is_connected = True
            logger.info("Successfully connected to MongoDB database.")
        except Exception as e:
            logger.warning(f"MongoDB live connection unavailable ({e}). Using in-memory fallback simulation.")
            self._is_connected = False

    def init_indexes(self):
        if self._is_connected:
            courses_coll = self._db["courses"]
            courses_coll.create_index("course_id", unique=True)
            courses_coll.create_index("code", unique=True)
            courses_coll.create_index([("has_lab", 1), ("has_exam", 1)])

    def insert_course_document(self, doc: Dict[str, Any]):
        if self._is_connected:
            self._db["courses"].update_one(
                {"course_id": doc["course_id"]},
                {"$set": doc},
                upsert=True
            )
        else:
            self._mock_collection = [c for c in self._mock_collection if c["course_id"] != doc["course_id"]]
            self._mock_collection.append(doc)

    def insert_batch(self, docs: List[Dict[str, Any]]):
        for doc in docs:
            self.insert_course_document(doc)

    def find_courses_with_lab_and_exam(self) -> List[Dict[str, Any]]:
        """
        Required Query: Courses that have both a lab and an exam component.
        Demonstrates querying flexible polymorphic documents in MongoDB.
        """
        if self._is_connected:
            cursor = self._db["courses"].find(
                {
                    "has_lab": True,
                    "has_exam": True
                },
                {"_id": 0, "course_id": 1, "code": 1, "title": 1, "has_lab": 1, "has_exam": 1, "grading_rubric": 1}
            )
            return list(cursor)
        else:
            return [
                {
                    "course_id": c["course_id"],
                    "code": c["code"],
                    "title": c["title"],
                    "has_lab": c.get("has_lab", False),
                    "has_exam": c.get("has_exam", False),
                    "grading_rubric": c.get("grading_rubric")
                }
                for c in self._mock_collection
                if c.get("has_lab") is True and c.get("has_exam") is True
            ]

    def get_course_description(self, course_id: int) -> Optional[Dict[str, Any]]:
        if self._is_connected:
            return self._db["courses"].find_one({"course_id": course_id}, {"_id": 0})
        for c in self._mock_collection:
            if c["course_id"] == course_id:
                return c
        return None

    def close(self):
        if self._client:
            self._client.close()
            self._client = None
            self._is_connected = False
