"""
Unit Tests for MongoDB Course Document Queries.
Verifies flexible document filtering: finding courses that have both a lab and an exam.
"""

from src.stores.mongo_client import MongoClient


def test_mongo_lab_and_exam_query():
    mongo = MongoClient()
    mongo.connect()

    # Seed mock polymorphic documents
    mongo.insert_batch([
        {"course_id": 1, "code": "CS101", "title": "Intro CS", "has_lab": True, "has_exam": True, "grading_rubric": {"exam": 50, "lab": 50}},
        {"course_id": 2, "code": "CS201", "title": "Algorithms", "has_lab": False, "has_exam": True, "grading_rubric": {"exam": 100}},
        {"course_id": 3, "code": "CS401", "title": "Distributed Systems", "has_lab": True, "has_exam": False, "has_project": True},
        {"course_id": 4, "code": "ECE201", "title": "Embedded Systems", "has_lab": True, "has_exam": True, "grading_rubric": {"exam": 40, "lab": 60}},
    ])

    results = mongo.find_courses_with_lab_and_exam()
    codes = {r["code"] for r in results}

    assert "CS101" in codes
    assert "ECE201" in codes
    assert "CS201" not in codes
    assert "CS401" not in codes


import unittest


class TestMongoQueries(unittest.TestCase):
    def test_query(self):
        test_mongo_lab_and_exam_query()
