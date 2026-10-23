"""
Integration Tests for CourseEnrolmentAdvisor Decision Engine.
Verifies end-to-end multi-store decision making (Postgres + Neo4j + Redis + pgvector/Qdrant).
"""

from src.stores.postgres_client import PostgresClient
from src.stores.mongo_client import MongoClient
from src.stores.redis_client import RedisClient
from src.stores.neo4j_client import Neo4jClient
from src.stores.vector_pg import PgVectorClient
from src.stores.vector_qdrant import QdrantStoreClient
from src.advisor import CourseEnrolmentAdvisor


def test_advisor_eligibility_decision_flow():
    pg = PostgresClient()
    mongo = MongoClient()
    redis = RedisClient()
    neo = Neo4jClient()
    pg_vec = PgVectorClient(postgres_client=pg)
    qdrant = QdrantStoreClient()

    pg.connect()
    mongo.connect()
    redis.connect()
    neo.connect()
    qdrant.connect()

    advisor = CourseEnrolmentAdvisor(pg, mongo, redis, neo, pg_vec, qdrant)

    # Setup section and mock data
    pg._mock_data["sections"][10] = {"id": 10, "course_id": 2, "capacity": 20, "seats_taken": 15}
    pg._mock_data["courses"][2] = {"id": 2, "code": "CS102", "title": "Data Structures", "credits": 4, "semester": "Fall"}

    neo.sync_course_catalog(
        courses=[
            {"id": 1, "code": "CS101", "title": "Intro CS", "credits": 4, "semester": "Fall"},
            {"id": 2, "code": "CS102", "title": "Data Structures", "credits": 4, "semester": "Fall"}
        ],
        prerequisites=[{"course_id": 2, "prerequisite_id": 1}]
    )

    # 1. Student without prerequisite CS101 -> REJECTED_PREREQUISITES_NOT_MET
    res1 = advisor.check_eligibility(student_id=50, course_id=2, section_id=10)
    assert res1["decision"] == "REJECTED_PREREQUISITES_NOT_MET"

    # 2. Student completes prerequisite CS101 -> APPROVED
    neo.sync_student_grades([{"student_id": 50, "course_id": 1, "grade": "A", "passed": True}])
    res2 = advisor.check_eligibility(student_id=50, course_id=2, section_id=10)
    assert res2["decision"] == "APPROVED"
    assert res2["seats_remaining"] == 5

    # 3. Enrol student via advisor
    exec_res = advisor.execute_enrolment(student_id=50, course_id=2, section_id=10)
    assert exec_res["success"] is True

    # 4. Attempting to enrol again -> REJECTED_ALREADY_ENROLLED
    res3 = advisor.check_eligibility(student_id=50, course_id=2, section_id=10)
    assert res3["decision"] == "REJECTED_ALREADY_ENROLLED"


import unittest


class TestAdvisorEligibility(unittest.TestCase):
    def test_decision_flow(self):
        test_advisor_eligibility_decision_flow()
