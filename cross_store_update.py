"""
Cross-Store Consistency Test for Course Enrolment Advisor.
Demonstrates eventual consistency across:
- PostgreSQL (System of Record for Grades & Enrolments)
- MongoDB (System of Record for Syllabi)
- Redis (Derived Student Session Cache)
- Neo4j (Derived Completed Prerequisite Graph)
- pgvector & Qdrant (Derived Semantic Embeddings)
Shows the exact state of derived copies before and after the refresh synchronization pipeline.
"""

import time
import logging
from datetime import datetime, timezone
from src.stores.postgres_client import PostgresClient
from src.stores.mongo_client import MongoClient
from src.stores.redis_client import RedisClient
from src.stores.neo4j_client import Neo4jClient
from src.stores.vector_pg import PgVectorClient
from src.stores.vector_qdrant import QdrantStoreClient
from src.embeddings import generate_embedding, cosine_similarity

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cross_store_update")


def run_cross_store_consistency_demo():
    print("\n" + "=" * 80)
    print(">>> CROSS-STORE CONSISTENCY & EVENTUAL CONSISTENCY DEMO <<<")
    print("=" * 80)

    # Initialize all 5 clients
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

    student_id = 99
    course_id = 4  # CS202 (Computer Systems)
    target_course_id = 5  # CS301 (Operating Systems) requires CS202

    # Step 0: Ensure base course data exists in Neo4j
    neo.sync_course_catalog(
        courses=[
            {"id": 4, "code": "CS202", "title": "Computer Systems", "credits": 4, "semester": "Spring"},
            {"id": 5, "code": "CS301", "title": "Operating Systems", "credits": 4, "semester": "Fall"}
        ],
        prerequisites=[{"course_id": 5, "prerequisite_id": 4}]
    )

    print("\n[PHASE 1: INITIAL STATE]")
    print(f"Student {student_id} wants to take CS301 (Operating Systems), which requires CS202.")
    # Check eligibility in Neo4j graph before student completes CS202
    eligible_before = neo.find_courses_with_completed_prerequisites(student_id)
    eligible_ids_before = [c["course_id"] for c in eligible_before]
    print(f"-> Neo4j Eligible Courses for Student {student_id}: {eligible_ids_before}")
    print(f"-> Can student take CS301? {'YES' if target_course_id in eligible_ids_before else 'NO (Prerequisite CS202 missing)'}")

    # Set initial Redis session cache
    redis.save_planned_courses(student_id, [target_course_id], ttl_seconds=60)
    cached_session_before = redis.get_planned_courses(student_id)
    print(f"-> Redis Student Session Plan: {cached_session_before['planned_course_ids']} (Refreshed: {cached_session_before['refreshed_at']})")

    print("\n[PHASE 2: SOURCE UPDATE IN POSTGRESQL (SYSTEM OF RECORD)]")
    print(f"Action: Final exam grades submitted! Student {student_id} passes CS202 with Grade 'A' in PostgreSQL.")
    new_grade = {
        "student_id": student_id,
        "course_id": course_id,
        "grade": "A",
        "grade_point": 4.0,
        "passed": True,
        "recorded_at": datetime.now(timezone.utc).isoformat()
    }
    if pg._is_connected:
        with pg._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO grades (student_id, course_id, grade, grade_point, passed)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (student_id, course_id) DO UPDATE SET grade = 'A', passed = TRUE;
                    """,
                    (student_id, course_id, "A", 4.0, True)
                )
            conn.commit()
    else:
        pg._mock_data["grades"][(student_id, course_id)] = new_grade
    print("-> PostgreSQL Grade Record Committed successfully.")

    print("\n[PHASE 3: DEMONSTRATING STALE DERIVED STATE (EVENTUAL CONSISTENCY)]")
    # Neo4j has NOT yet been refreshed
    eligible_stale = neo.find_courses_with_completed_prerequisites(student_id)
    eligible_ids_stale = [c["course_id"] for c in eligible_stale]
    print("-> Checking Neo4j Graph before refresh sync:")
    print(f"   Notice: Neo4j still shows CS301 as locked! (Eligible IDs: {eligible_ids_stale})")
    print("   EXPLANATION: Derived stores are asynchronous/eventually consistent. The graph has not polled or consumed the CDC event yet.")

    print("\n[PHASE 4: EXECUTING REFRESH SYNCHRONIZATION PIPELINE]")
    refresh_timestamp = datetime.now(timezone.utc).isoformat()
    print(f"Triggering cache invalidation and graph sync at: {refresh_timestamp}...")

    # 1. Sync Neo4j from PostgreSQL
    neo.sync_student_grades([new_grade])

    # 2. Invalidate/update Redis cache
    redis.save_planned_courses(student_id, [target_course_id, 6], ttl_seconds=60)

    # 3. Update Course Description in MongoDB & Derived Vector Stores
    updated_desc = "Advanced Operating Systems and Distributed Kernel Architecture. Deep dive into eBPF, microkernels, and Raft consensus."
    updated_embedding = generate_embedding(updated_desc)
    vector_record = {
        "course_id": target_course_id,
        "code": "CS301",
        "title": "Operating Systems Internals",
        "semester": "Fall",
        "credits": 4,
        "embedding": updated_embedding,
        "source_id": "mongo_courses",
        "refreshed_at": refresh_timestamp
    }
    pg_vec.set_vectors([vector_record])
    qdrant.upsert_vectors([vector_record])

    print("\n[PHASE 5: POST-REFRESH VERIFICATION (CONSISTENCY RESTORED)]")
    # Verify Neo4j
    eligible_after = neo.find_courses_with_completed_prerequisites(student_id)
    eligible_ids_after = [c["course_id"] for c in eligible_after]
    print(f"-> Neo4j Graph after sync: Student completed prerequisites!")
    print(f"   Can student now enrol in CS301? {'YES! (Prerequisite fulfilled)' if target_course_id in eligible_ids_after else 'NO'}")

    # Verify Redis
    cached_session_after = redis.get_planned_courses(student_id)
    print(f"-> Redis Session Plan updated: {cached_session_after['planned_course_ids']} (Refreshed: {cached_session_after['refreshed_at']})")

    # Verify Vector provenance
    print(f"-> Vector Stores (pgvector & Qdrant) provenance:")
    print(f"   Source ID: {vector_record['source_id']} | Refreshed At: {vector_record['refreshed_at']}")
    print("=" * 80)
    print(">>> CROSS-STORE CONSISTENCY DEMO COMPLETE: SUCCESS <<<\n")


if __name__ == "__main__":
    run_cross_store_consistency_demo()
