"""
Unit Tests for Neo4j Prerequisite and Graph Traversal Queries.
Verifies finding eligible courses based on completed prerequisites, course equivalencies,
and shortest prerequisite path calculations.
"""

from src.stores.neo4j_client import Neo4jClient


def test_neo4j_completed_prerequisites():
    neo = Neo4jClient(use_mock=True)
    neo.connect()

    courses = [
        {"id": 1, "code": "CS101", "title": "Intro CS", "credits": 4, "semester": "Fall"},
        {"id": 2, "code": "CS102", "title": "Data Structures", "credits": 4, "semester": "Spring"},
        {"id": 3, "code": "CS201", "title": "Algorithms", "credits": 4, "semester": "Fall"},
    ]
    prereqs = [
        {"course_id": 2, "prerequisite_id": 1},  # CS102 requires CS101
        {"course_id": 3, "prerequisite_id": 2},  # CS201 requires CS102
    ]
    neo.sync_course_catalog(courses, prereqs)

    # Student 10 completed CS101
    neo.sync_student_grades([{"student_id": 10, "course_id": 1, "grade": "A", "passed": True}])

    eligible = neo.find_courses_with_completed_prerequisites(student_id=10)
    eligible_codes = [c["code"] for c in eligible]

    # CS102 is unlocked because CS101 is completed! CS201 is still locked (requires CS102).
    assert "CS102" in eligible_codes
    assert "CS201" not in eligible_codes
    assert "CS101" not in eligible_codes  # Already completed


def test_neo4j_course_equivalence():
    neo = Neo4jClient(use_mock=True)
    neo.connect()

    courses = [
        {"id": 10, "code": "MATH201", "title": "Linear Algebra", "credits": 3, "semester": "Fall"},
        {"id": 11, "code": "MATH205", "title": "Applied Linear Algebra", "credits": 3, "semester": "Fall"},
        {"id": 12, "code": "DATA301", "title": "Machine Learning", "credits": 4, "semester": "Spring"},
    ]
    prereqs = [
        {"course_id": 12, "prerequisite_id": 10}  # DATA301 requires MATH201
    ]
    equivalencies = [
        {"course_id_1": 10, "course_id_2": 11}  # MATH201 == MATH205
    ]
    neo.sync_course_catalog(courses, prereqs, equivalencies)

    # Student took MATH205 (the equivalent course)
    neo.sync_student_grades([{"student_id": 20, "course_id": 11, "grade": "B+", "passed": True}])

    eligible = neo.find_courses_with_completed_prerequisites(student_id=20)
    eligible_codes = [c["code"] for c in eligible]

    assert "DATA301" in eligible_codes


def test_neo4j_shortest_prerequisite_path():
    neo = Neo4jClient(use_mock=True)
    neo.connect()

    courses = [
        {"id": 1, "code": "CS101", "title": "Intro CS", "credits": 4, "semester": "Fall"},
        {"id": 2, "code": "CS102", "title": "Data Structures", "credits": 4, "semester": "Spring"},
        {"id": 3, "code": "CS201", "title": "Algorithms", "credits": 4, "semester": "Fall"},
        {"id": 4, "code": "CS401", "title": "Advanced Systems", "credits": 4, "semester": "Fall"},
    ]
    prereqs = [
        {"course_id": 2, "prerequisite_id": 1},
        {"course_id": 3, "prerequisite_id": 2},
        {"course_id": 4, "prerequisite_id": 3},
    ]
    neo.sync_course_catalog(courses, prereqs)

    res = neo.find_shortest_prerequisite_path("CS101", "CS401")
    assert res["found"] is True
    assert res["path_length"] == 3
    path_codes = [n["code"] for n in res["path"]]
    assert path_codes == ["CS101", "CS102", "CS201", "CS401"]


import unittest


class TestNeo4jPrereqs(unittest.TestCase):
    def test_prereqs(self):
        test_neo4j_completed_prerequisites()

    def test_equivalence(self):
        test_neo4j_course_equivalence()

    def test_shortest_path(self):
        test_neo4j_shortest_prerequisite_path()
