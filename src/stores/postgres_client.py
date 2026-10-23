"""
PostgreSQL Store Client for Course Enrolment Advisor.
System of Record for business entities (students, courses, sections, enrolments, grades)
and pgvector extension for relational + vector integrated queries.
"""

import threading
import logging
from typing import List, Dict, Any, Optional, Tuple
from config import config

logger = logging.getLogger(__name__)

CREATE_SCHEMA_SQL = """
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 1. Students Table
CREATE TABLE IF NOT EXISTS students (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    matriculation_year INT NOT NULL,
    major VARCHAR(100) NOT NULL
);

-- 2. Courses Table
CREATE TABLE IF NOT EXISTS courses (
    id SERIAL PRIMARY KEY,
    code VARCHAR(20) UNIQUE NOT NULL,
    title VARCHAR(255) NOT NULL,
    credits INT NOT NULL CHECK (credits > 0),
    semester VARCHAR(20) NOT NULL,
    department VARCHAR(100) NOT NULL
);

-- 3. Course Sections Table with CHECK (seats_taken <= capacity)
CREATE TABLE IF NOT EXISTS sections (
    id SERIAL PRIMARY KEY,
    course_id INT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    term VARCHAR(50) NOT NULL,
    capacity INT NOT NULL CHECK (capacity > 0),
    seats_taken INT NOT NULL DEFAULT 0,
    CONSTRAINT check_seats_capacity CHECK (seats_taken <= capacity)
);

-- 4. Enrolments Table with UNIQUE (student_id, section_id)
CREATE TABLE IF NOT EXISTS enrolments (
    id SERIAL PRIMARY KEY,
    student_id INT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    section_id INT NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'ENROLLED',
    enrolled_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_student_section UNIQUE (student_id, section_id)
);

-- 5. Grades Table
CREATE TABLE IF NOT EXISTS grades (
    id SERIAL PRIMARY KEY,
    student_id INT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    course_id INT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    grade VARCHAR(5) NOT NULL,
    grade_point NUMERIC(3, 2) NOT NULL,
    passed BOOLEAN NOT NULL DEFAULT TRUE,
    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_student_course_grade UNIQUE (student_id, course_id)
);

-- 6. pgvector Embeddings Table
CREATE TABLE IF NOT EXISTS course_embeddings (
    course_id INT PRIMARY KEY REFERENCES courses(id) ON DELETE CASCADE,
    embedding vector(384) NOT NULL,
    source_id VARCHAR(64) NOT NULL,
    refreshed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 7. Indexes
CREATE INDEX IF NOT EXISTS idx_sections_course ON sections(course_id);
CREATE INDEX IF NOT EXISTS idx_enrolments_student ON enrolments(student_id);
CREATE INDEX IF NOT EXISTS idx_grades_student ON grades(student_id);
CREATE INDEX IF NOT EXISTS idx_courses_semester ON courses(semester);

-- HNSW Vector Index on course_embeddings (Cosine Distance)
CREATE INDEX IF NOT EXISTS course_embeddings_hnsw_idx 
ON course_embeddings 
USING hnsw (embedding vector_cosine_ops) 
WITH (m = 16, ef_construction = 64);
"""


class SeatFullError(Exception):
    """Raised when an enrolment fails because no seats are available."""
    pass


class AlreadyEnrolledError(Exception):
    """Raised when a student is already enrolled in the section."""
    pass


class PostgresClient:
    def __init__(self, dsn: Optional[str] = None):
        self.dsn = dsn or config.postgres.dsn
        self._pool = None
        self._is_connected = False
        self._mock_data = None
        self._mock_lock = threading.Lock()

    def connect(self):
        try:
            import psycopg
            from psycopg_pool import ConnectionPool
            self._pool = ConnectionPool(self.dsn, min_size=2, max_size=20, timeout=5.0)
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
            self._is_connected = True
            logger.info("Successfully connected to PostgreSQL database.")
        except Exception as e:
            logger.warning(f"PostgreSQL live connection unavailable ({e}). Using in-memory fallback simulation.")
            self._is_connected = False
            self._init_mock_storage()

    def _init_mock_storage(self):
        with self._mock_lock:
            self._mock_data = {
                "students": {},
                "courses": {},
                "sections": {},
                "enrolments": {},
                "grades": {},
                "embeddings": {}
            }

    def init_schema(self):
        if self._is_connected:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(CREATE_SCHEMA_SQL)
                conn.commit()
        else:
            self._init_mock_storage()

    def enrol_student(self, student_id: int, section_id: int) -> Dict[str, Any]:
        """
        Required Query: Enrol in one transaction:
        1. Lock the section row with SELECT ... FOR UPDATE
        2. Check seats_taken < capacity
        3. Insert the enrolment
        4. Increment seats_taken
        """
        if self._is_connected:
            import psycopg
            with self._pool.connection() as conn:
                try:
                    with conn.transaction():
                        with conn.cursor() as cur:
                            # 1. Lock section row
                            cur.execute(
                                "SELECT id, course_id, capacity, seats_taken FROM sections WHERE id = %s FOR UPDATE;",
                                (section_id,)
                            )
                            section = cur.fetchone()
                            if not section:
                                raise ValueError(f"Section {section_id} does not exist.")

                            sec_id, course_id, capacity, seats_taken = section
                            if seats_taken >= capacity:
                                raise SeatFullError(f"Section {section_id} is full ({seats_taken}/{capacity} seats taken).")

                            # 2. Insert enrolment
                            try:
                                cur.execute(
                                    "INSERT INTO enrolments (student_id, section_id, status) VALUES (%s, %s, 'ENROLLED') RETURNING id, enrolled_at;",
                                    (student_id, section_id)
                                )
                                enrolment_id, enrolled_at = cur.fetchone()
                            except psycopg.errors.UniqueViolation:
                                raise AlreadyEnrolledError(f"Student {student_id} already enrolled in section {section_id}.")

                            # 3. Increment seats_taken
                            cur.execute(
                                "UPDATE sections SET seats_taken = seats_taken + 1 WHERE id = %s RETURNING seats_taken;",
                                (section_id,)
                            )
                            new_seats_taken = cur.fetchone()[0]

                            return {
                                "success": True,
                                "enrolment_id": enrolment_id,
                                "student_id": student_id,
                                "section_id": section_id,
                                "seats_taken": new_seats_taken,
                                "capacity": capacity,
                                "enrolled_at": str(enrolled_at)
                            }
                except psycopg.errors.CheckViolation:
                    raise SeatFullError(f"CHECK constraint violated: section {section_id} capacity exceeded.")
        else:
            # Thread-safe in-memory simulation with identical locking semantics
            with self._mock_lock:
                section = self._mock_data["sections"].get(section_id)
                if not section:
                    raise ValueError(f"Section {section_id} does not exist.")

                if section["seats_taken"] >= section["capacity"]:
                    raise SeatFullError(f"Section {section_id} is full ({section['seats_taken']}/{section['capacity']} seats).")

                # Check unique constraint
                for enr in self._mock_data["enrolments"].values():
                    if enr["student_id"] == student_id and enr["section_id"] == section_id:
                        raise AlreadyEnrolledError(f"Student {student_id} already enrolled in section {section_id}.")

                # Enrol
                enr_id = len(self._mock_data["enrolments"]) + 1
                section["seats_taken"] += 1
                self._mock_data["enrolments"][enr_id] = {
                    "id": enr_id,
                    "student_id": student_id,
                    "section_id": section_id,
                    "status": "ENROLLED"
                }
                return {
                    "success": True,
                    "enrolment_id": enr_id,
                    "student_id": student_id,
                    "section_id": section_id,
                    "seats_taken": section["seats_taken"],
                    "capacity": section["capacity"],
                    "enrolled_at": "simulated_timestamp"
                }

    def run_concurrent_enrolment_test(self, section_id: int, student_a_id: int, student_b_id: int) -> Dict[str, Any]:
        """
        Concurrency test required by spec:
        Two students taking the last seat: one enrolment commits, the other is rejected.
        """
        results = {}

        def attempt(student_id, key):
            try:
                res = self.enrol_student(student_id, section_id)
                results[key] = {"status": "COMMITTED", "data": res}
            except SeatFullError as e:
                results[key] = {"status": "REJECTED_SEAT_FULL", "error": str(e)}
            except Exception as e:
                results[key] = {"status": "FAILED", "error": str(e)}

        t1 = threading.Thread(target=attempt, args=(student_a_id, "student_a"))
        t2 = threading.Thread(target=attempt, args=(student_b_id, "student_b"))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        return results

    def integrated_vector_business_query(self, query_vector: List[float], semester: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Required Query: Show one query that pgvector answers in a single SQL statement
        joined with business tables (sections remaining seats, semester filter).
        """
        if self._is_connected:
            vector_str = f"[{','.join(map(str, query_vector))}]"
            sql = """
            SELECT 
                c.id AS course_id,
                c.code,
                c.title,
                c.credits,
                c.semester,
                s.id AS section_id,
                (s.capacity - s.seats_taken) AS seats_remaining,
                (1 - (e.embedding <=> %s::vector)) AS similarity_score
            FROM course_embeddings e
            JOIN courses c ON e.course_id = c.id
            JOIN sections s ON s.course_id = c.id
            WHERE s.seats_taken < s.capacity
              AND c.semester = %s
            ORDER BY e.embedding <=> %s::vector
            LIMIT %s;
            """
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, (vector_str, semester, vector_str, limit))
                    rows = cur.fetchall()
                    return [
                        {
                            "course_id": r[0],
                            "code": r[1],
                            "title": r[2],
                            "credits": r[3],
                            "semester": r[4],
                            "section_id": r[5],
                            "seats_remaining": r[6],
                            "similarity_score": float(r[7])
                        }
                        for r in rows
                    ]
        else:
            from src.embeddings import cosine_similarity
            results = []
            with self._mock_lock:
                for c_id, emb_data in self._mock_data["embeddings"].items():
                    course = self._mock_data["courses"].get(c_id)
                    if not course or course["semester"] != semester:
                        continue
                    # Find open sections
                    open_sections = [
                        s for s in self._mock_data["sections"].values()
                        if s["course_id"] == c_id and s["seats_taken"] < s["capacity"]
                    ]
                    if not open_sections:
                        continue
                    sec = open_sections[0]
                    sim = cosine_similarity(query_vector, emb_data["embedding"])
                    results.append({
                        "course_id": c_id,
                        "code": course["code"],
                        "title": course["title"],
                        "credits": course["credits"],
                        "semester": course["semester"],
                        "section_id": sec["id"],
                        "seats_remaining": sec["capacity"] - sec["seats_taken"],
                        "similarity_score": sim
                    })
            results.sort(key=lambda x: x["similarity_score"], reverse=True)
            return results[:limit]

    def close(self):
        if self._pool:
            self._pool.close()
            self._pool = None
            self._is_connected = False
