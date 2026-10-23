"""
Course Enrolment Advisor Decision Engine.
Unites all five database stores to make enrolment decisions and interest-based recommendations:
- PostgreSQL: Enrolment ACID transactions and section capacities (System of Record)
- MongoDB: Flexible course syllabi and lab/exam components (System of Record)
- Redis: Student active session planned courses cache (Derived)
- Neo4j: Prerequisite fulfillment and shortest path graph analysis (Derived)
- pgvector / Qdrant: Semantic course discovery with metadata filtering (Derived)
"""

from typing import List, Dict, Any, Optional
from src.stores.postgres_client import PostgresClient, SeatFullError, AlreadyEnrolledError
from src.stores.mongo_client import MongoClient
from src.stores.redis_client import RedisClient
from src.stores.neo4j_client import Neo4jClient
from src.stores.vector_pg import PgVectorClient
from src.stores.vector_qdrant import QdrantStoreClient
from src.embeddings import generate_embedding


class CourseEnrolmentAdvisor:
    def __init__(
        self,
        postgres: PostgresClient,
        mongo: MongoClient,
        redis: RedisClient,
        neo4j: Neo4jClient,
        pg_vector: PgVectorClient,
        qdrant: QdrantStoreClient
    ):
        self.pg = postgres
        self.mongo = mongo
        self.redis = redis
        self.neo4j = neo4j
        self.pg_vector = pg_vector
        self.qdrant = qdrant

    def check_eligibility(self, student_id: int, course_id: int, section_id: int) -> Dict[str, Any]:
        """
        Decision Workflow:
        Decides whether a student may enrol in a course.
        1. Query Neo4j to verify that all prerequisites for course_id are satisfied.
        2. Query PostgreSQL to check whether section_id has remaining capacity (seats_taken < capacity).
        3. Check if student is already enrolled in section.
        """
        # Step 1: Check prerequisites via Neo4j
        eligible_courses = self.neo4j.find_courses_with_completed_prerequisites(student_id)
        eligible_ids = {c["course_id"] for c in eligible_courses}

        prereq_met = course_id in eligible_ids

        # Step 2: Check section seat availability via PostgreSQL
        # Check seats in postgres
        seat_available = False
        seats_remaining = 0
        capacity = 0
        seats_taken = 0

        if self.pg._is_connected:
            with self.pg._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT capacity, seats_taken FROM sections WHERE id = %s;", (section_id,))
                    row = cur.fetchone()
                    if row:
                        capacity, seats_taken = row
                        seats_remaining = capacity - seats_taken
                        seat_available = seats_remaining > 0
        else:
            sec = self.pg._mock_data["sections"].get(section_id)
            if sec:
                capacity = sec["capacity"]
                seats_taken = sec["seats_taken"]
                seats_remaining = capacity - seats_taken
                seat_available = seats_remaining > 0

        # Step 3: Check duplicate enrolment
        already_enrolled = False
        if self.pg._is_connected:
            with self.pg._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM enrolments WHERE student_id = %s AND section_id = %s;",
                        (student_id, section_id)
                    )
                    already_enrolled = (cur.fetchone() is not None)
        else:
            for enr in self.pg._mock_data["enrolments"].values():
                if enr["student_id"] == student_id and enr["section_id"] == section_id:
                    already_enrolled = True
                    break

        if already_enrolled:
            decision = "REJECTED_ALREADY_ENROLLED"
            reason = f"Student {student_id} is already enrolled in section {section_id}."
        elif not prereq_met:
            decision = "REJECTED_PREREQUISITES_NOT_MET"
            reason = f"Student {student_id} has not completed all prerequisites for course {course_id}."
        elif not seat_available:
            decision = "REJECTED_SECTION_FULL"
            reason = f"Section {section_id} is full ({seats_taken}/{capacity} seats filled)."
        else:
            decision = "APPROVED"
            reason = f"Prerequisites verified and {seats_remaining} seats remaining."

        return {
            "student_id": student_id,
            "course_id": course_id,
            "section_id": section_id,
            "decision": decision,
            "reason": reason,
            "prerequisites_met": prereq_met,
            "seats_available": seat_available,
            "seats_remaining": seats_remaining
        }

    def execute_enrolment(self, student_id: int, course_id: int, section_id: int) -> Dict[str, Any]:
        """
        Executes an enrolment: validates eligibility first, then executes the ACID locking transaction.
        """
        eligibility = self.check_eligibility(student_id, course_id, section_id)
        if eligibility["decision"] != "APPROVED":
            return {"success": False, "eligibility": eligibility}

        tx_result = self.pg.enrol_student(student_id, section_id)
        # Update Redis session planned courses
        session = self.redis.get_planned_courses(student_id)
        if session:
            planned = session.get("planned_course_ids", [])
            if course_id in planned:
                planned.remove(course_id)
                self.redis.save_planned_courses(student_id, planned)

        return {"success": True, "eligibility": eligibility, "transaction": tx_result}

    def recommend_courses(
        self,
        student_id: int,
        interest_text: str,
        semester: str,
        backend: str = "pgvector",
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Suggests courses that match the student's interest, filtered by semester.
        """
        query_vec = generate_embedding(interest_text)

        if backend == "pgvector":
            recommendations = self.pg.integrated_vector_business_query(
                query_vector=query_vec,
                semester=semester,
                limit=limit
            )
        else:
            recommendations = self.qdrant.two_step_vector_business_query(
                query_vector=query_vec,
                semester=semester,
                postgres_client=self.pg,
                limit=limit
            )

        # Cross-reference with student prerequisites from Neo4j
        eligible_courses = self.neo4j.find_courses_with_completed_prerequisites(student_id)
        eligible_ids = {c["course_id"] for c in eligible_courses}

        for rec in recommendations:
            rec["prerequisites_satisfied"] = rec["course_id"] in eligible_ids
            rec["can_enrol_now"] = rec["prerequisites_satisfied"] and (rec["seats_remaining"] > 0)

        return recommendations
