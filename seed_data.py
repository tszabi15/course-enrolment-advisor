"""
Seed Data Generator for Course Enrolment Advisor.
Generates realistic university curriculum data (200-1000 records per store),
populates Systems of Record (PostgreSQL, MongoDB), and synchronizes Derived Stores
(Redis, Neo4j, pgvector, Qdrant) with complete data provenance tracking.
"""

import json
import random
import logging
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, timezone

from config import config
from src.models import (
    Student, Course, Section, Enrolment, GradeRecord,
    MongoCourseDocument, PlannedCoursesSession, CoursePrerequisite
)
from src.embeddings import generate_embeddings_batch
from src.stores.postgres_client import PostgresClient
from src.stores.mongo_client import MongoClient
from src.stores.redis_client import RedisClient
from src.stores.neo4j_client import Neo4jClient
from src.stores.vector_pg import PgVectorClient
from src.stores.vector_qdrant import QdrantStoreClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_data")

random.seed(42)  # For reproducible data generation


# ------------------------------------------------------------------------------
# Curriculum Generator Definitions
# ------------------------------------------------------------------------------

DEPARTMENTS = [
    ("CS", "Computer Science"),
    ("DATA", "Data Science"),
    ("MATH", "Mathematics"),
    ("ECE", "Electrical and Computer Engineering"),
    ("STAT", "Statistics"),
    ("PHYS", "Physics"),
    ("BUS", "Business and Information Systems")
]

SEMESTERS = ["Fall", "Spring", "Summer"]

COURSE_TEMPLATES = [
    # CS Core & Advanced
    ("CS", 101, "Introduction to Programming and Algorithms", "Fundamental programming paradigms, control flow, recursion, and algorithm analysis in Python and C.", 4, True, True, False),
    ("CS", 102, "Object-Oriented Design and Data Structures", "Abstract data types, linked lists, trees, graphs, heaps, and object-oriented architectural patterns.", 4, True, True, True),
    ("CS", 201, "Algorithms and Complexity Theory", "Divide-and-conquer, dynamic programming, greedy algorithms, NP-completeness, and graph search strategies.", 4, False, True, False),
    ("CS", 202, "Computer Systems and Low-Level Programming", "C programming, memory layout, pointers, assembly, processor architecture, and caching mechanisms.", 4, True, True, True),
    ("CS", 301, "Operating Systems Internals", "Concurrency primitives, deadlocks, virtual memory paging, process scheduling, and file systems.", 4, True, True, True),
    ("CS", 302, "Database Systems and Query Optimization", "Relational algebra, SQL, B+ trees, ACID transactions, WAL logging, buffer pool managers, and query plans.", 3, True, True, True),
    ("CS", 401, "Distributed Systems and Cloud Architecture", "Consensus algorithms, Raft, Paxos, CAP theorem, eventual consistency, RPCs, and container orchestration.", 4, True, False, True),
    ("CS", 402, "Computer Networks and Protocol Engineering", "OSI stack, TCP/IP congestion control, routing algorithms, socket programming, and network security.", 3, True, True, False),
    ("CS", 405, "Compiler Construction and Language Runtimes", "Lexical analysis, AST generation, LLVM IR, garbage collection, and register allocation.", 4, True, True, True),
    ("CS", 450, "Computer Graphics and GPU Acceleration", "OpenGL, ray tracing, shader programming, matrix transformations, and Vulkan pipelines.", 3, True, True, True),
    ("CS", 501, "Advanced Cloud Infrastructure and Microservices", "Service meshes, distributed tracing, Kubernetes operators, multi-tenant databases, and chaos engineering.", 4, True, False, True),
    ("CS", 502, "Parallel Computing and High Performance Architectures", "OpenMP, MPI, CUDA kernels, lock-free data structures, memory barriers, and SIMD vectorization.", 4, True, True, True),
    
    # Data Science & AI
    ("DATA", 101, "Foundations of Data Analysis", "Exploratory data analysis, statistical modeling, data cleaning, and visualization using Pandas and Seaborn.", 3, True, True, False),
    ("DATA", 201, "Statistical Learning and Inference", "Hypothesis testing, regression analysis, ANOVA, maximum likelihood estimation, and bootstrap techniques.", 3, False, True, False),
    ("DATA", 301, "Machine Learning Principles", "Supervised and unsupervised learning, SVMs, random forests, boosting, gradient descent, and cross-validation.", 4, True, True, True),
    ("DATA", 401, "Deep Learning and Neural Architectures", "Backpropagation, CNNs, Transformers, attention mechanisms, loss functions, and PyTorch model training.", 4, True, True, True),
    ("DATA", 402, "Natural Language Processing and Large Language Models", "Tokenization, word embeddings, sequence-to-sequence models, fine-tuning, and vector similarity search.", 4, True, False, True),
    ("DATA", 405, "Computer Vision and Spatial Perception", "Edge detection, image classification, object detection (YOLO), semantic segmentation, and optical flow.", 4, True, True, True),
    ("DATA", 501, "Reinforcement Learning and Autonomous Agents", "Markov decision processes, Q-learning, policy gradients, actor-critic methods, and robotics simulation.", 4, True, False, True),
    
    # Mathematics & Statistics
    ("MATH", 101, "Single-Variable Calculus", "Limits, derivatives, integrals, fundamental theorem of calculus, and series expansions.", 4, False, True, False),
    ("MATH", 102, "Multivariable Calculus and Vector Fields", "Partial derivatives, multiple integrals, Stokes theorem, gradient fields, and Lagrange multipliers.", 4, False, True, False),
    ("MATH", 201, "Linear Algebra and Matrix Theory", "Vector spaces, subspaces, eigenvalues, eigenvectors, SVD decomposition, and orthogonal projections.", 3, False, True, False),
    ("MATH", 205, "Applied Linear Algebra for Computing", "Matrix factorizations, sparse matrices, QR decomposition, PageRank algorithm, and least squares.", 3, True, True, False),
    ("MATH", 301, "Discrete Mathematics and Graph Theory", "Combinatorics, Boolean algebra, graph coloring, Eulerian circuits, recurrence relations, and proofs.", 3, False, True, False),
    ("STAT", 201, "Probability Theory for Engineers", "Random variables, joint distributions, Central Limit Theorem, Poisson processes, and Markov chains.", 3, False, True, False),
    ("STAT", 301, "Bayesian Statistics and Monte Carlo Methods", "Prior and posterior distributions, MCMC, Gibbs sampling, hierarchical modeling, and Stan.", 3, True, True, False),
    
    # ECE & Systems
    ("ECE", 101, "Digital Logic Design and FPGA Synthesis", "Boolean algebra, combinational logic, flip-flops, state machines, Verilog HDL, and FPGA programming.", 4, True, True, False),
    ("ECE", 201, "Embedded Systems and Microcontrollers", "ARM Cortex architecture, interrupts, GPIOs, I2C, SPI, timers, and bare-metal firmware programming.", 4, True, True, True),
    ("ECE", 301, "Signal Processing and Fourier Analysis", "Discrete Fourier Transform, FFT, filter design, z-transform, convolution, and audio processing.", 3, True, True, False),
    ("ECE", 401, "Robotics Perception and Sensor Fusion", "Kalman filtering, lidar odometry, SLAM, ROS2 navigation, and IMU sensor integration.", 4, True, False, True),
    
    # Business & Systems
    ("BUS", 101, "Principles of Information Systems Management", "Enterprise systems, IT governance, digital transformation strategies, and organizational workflows.", 3, False, True, False),
    ("BUS", 201, "Technology Project Management and Agile Practices", "Scrum sprints, backlog grooming, risk management, stakeholder communication, and DevOps lifecycles.", 3, False, False, True),
    ("BUS", 301, "Business Analytics and Decision Support", "Dashboard design, KPI tracking, cohort retention analysis, SQL reporting, and executive metrics.", 3, True, True, True),
]


def generate_curriculum_catalog(total_courses: int = 300) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Generates 300 rich courses with realistic titles, descriptions, prerequisites, and equivalencies.
    """
    courses = []
    mongo_docs = []
    prerequisites = []
    equivalencies = []

    course_id = 1
    # 1. Add base template courses
    for dept, level, title, desc, credits, has_lab, has_exam, has_project in COURSE_TEMPLATES:
        sem = "Fall" if level % 2 == 1 else "Spring"
        code = f"{dept}{level}"
        courses.append({
            "id": course_id,
            "code": code,
            "title": title,
            "credits": credits,
            "semester": sem,
            "department": dept
        })
        mongo_docs.append({
            "course_id": course_id,
            "code": code,
            "title": title,
            "description": desc,
            "has_lab": has_lab,
            "has_exam": has_exam,
            "has_project": has_project,
            "reading_list": [f"Textbook on {title} (Edition {random.randint(2, 8)})", "Research Papers from ACM / IEEE"],
            "grading_rubric": {"exam": 50 if has_exam else 0, "lab": 30 if has_lab else 0, "project": 20 if has_project else 0}
        })
        course_id += 1

    # 2. Procedurally generate remaining courses to reach total_courses
    dept_names = [d[0] for d in DEPARTMENTS]
    while course_id <= total_courses:
        dept = random.choice(dept_names)
        num = random.randint(100, 599)
        code = f"{dept}{num}"
        # Avoid duplicate code
        if any(c["code"] == code for c in courses):
            continue
        sem = random.choice(SEMESTERS)
        credits = random.choice([3, 4])
        has_lab = random.choice([True, False, False])
        has_exam = random.choice([True, True, False])
        has_proj = random.choice([True, False])
        title = f"Topics in {dept} {num}: Advanced Study"
        desc = f"Comprehensive curriculum in {dept} focusing on modern theoretical principles, algorithmic paradigms, and industry applications. Covers semester topic {num}."

        courses.append({
            "id": course_id,
            "code": code,
            "title": title,
            "credits": credits,
            "semester": sem,
            "department": dept
        })
        mongo_docs.append({
            "course_id": course_id,
            "code": code,
            "title": title,
            "description": desc,
            "has_lab": has_lab,
            "has_exam": has_exam,
            "has_project": has_proj,
            "reading_list": [f"Selected readings for {code}"],
            "grading_rubric": {"exam": 50 if has_exam else 0, "lab": 25 if has_lab else 0, "project": 25 if has_proj else 0}
        })
        course_id += 1

    # Map code to id
    code_map = {c["code"]: c["id"] for c in courses}

    # Explicit Prerequisite Chains
    explicit_prereqs = [
        ("CS102", "CS101"),
        ("CS201", "CS102"),
        ("CS202", "CS101"),
        ("CS301", "CS202"),
        ("CS302", "CS201"),
        ("CS401", "CS301"),
        ("CS401", "CS302"),
        ("CS501", "CS401"),
        ("MATH102", "MATH101"),
        ("MATH201", "MATH101"),
        ("DATA301", "CS101"),
        ("DATA301", "MATH201"),
        ("DATA401", "DATA301"),
        ("DATA402", "DATA401"),
        ("DATA501", "DATA401"),
        ("ECE201", "ECE101"),
        ("ECE401", "ECE201"),
        ("ECE401", "DATA301"),
    ]

    for dep_code, req_code in explicit_prereqs:
        if dep_code in code_map and req_code in code_map:
            prerequisites.append({
                "course_id": code_map[dep_code],
                "prerequisite_id": code_map[req_code]
            })

    # Equivalencies: MATH201 equivalent to MATH205
    if "MATH201" in code_map and "MATH205" in code_map:
        equivalencies.append({
            "course_id_1": code_map["MATH201"],
            "course_id_2": code_map["MATH205"]
        })

    return courses, mongo_docs, prerequisites, equivalencies


def generate_students(num_students: int = 500) -> List[Dict[str, Any]]:
    first_names = ["Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Sam", "Chris", "Pat", "Robin",
                   "Emma", "Liam", "Sophia", "Noah", "Olivia", "James", "Ava", "Lucas", "Mia", "Ethan"]
    last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Martinez",
                  "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson"]
    majors = ["Computer Science", "Data Science", "Mathematics", "Electrical Engineering", "Statistics", "Business Analytics"]

    students = []
    for sid in range(1, num_students + 1):
        fn = random.choice(first_names)
        ln = random.choice(last_names)
        email = f"{fn.lower()}.{ln.lower()}{sid}@university.edu"
        year = random.choice([2023, 2024, 2025, 2026])
        major = random.choice(majors)
        students.append({
            "id": sid,
            "name": f"{fn} {ln}",
            "email": email,
            "matriculation_year": year,
            "major": major
        })
    return students


def generate_sections_and_enrolments(
    courses: List[Dict[str, Any]],
    students: List[Dict[str, Any]],
    num_sections: int = 400
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Generates sections with capacity, seats_taken, and initial enrolments.
    """
    sections = []
    enrolments = []
    enr_id = 1

    for sec_id in range(1, num_sections + 1):
        course = courses[(sec_id - 1) % len(courses)]
        term = f"2026-{course['semester']}"
        capacity = random.choice([15, 20, 25, 30, 40])
        # Random initial seats taken (less than capacity)
        seats_taken = random.randint(0, min(capacity - 1, 10))

        sections.append({
            "id": sec_id,
            "course_id": course["id"],
            "term": term,
            "capacity": capacity,
            "seats_taken": seats_taken
        })

        # Pre-enrol students to match seats_taken
        if seats_taken > 0:
            enrolled_students = random.sample(students, seats_taken)
            for s in enrolled_students:
                enrolments.append({
                    "id": enr_id,
                    "student_id": s["id"],
                    "section_id": sec_id,
                    "status": "ENROLLED"
                })
                enr_id += 1

    return sections, enrolments


def generate_grades(
    students: List[Dict[str, Any]],
    courses: List[Dict[str, Any]],
    num_grades: int = 800
) -> List[Dict[str, Any]]:
    """
    Generates historical student grades (used to derive completed courses in Neo4j).
    """
    grade_letter_map = [
        ("A", 4.0, True),
        ("A-", 3.7, True),
        ("B+", 3.3, True),
        ("B", 3.0, True),
        ("B-", 2.7, True),
        ("C+", 2.3, True),
        ("C", 2.0, True),
        ("F", 0.0, False)
    ]
    grades = []
    existing_pairs = set()

    # Pre-populate specific foundation courses for the first 100 students
    # (e.g. Student 1 passed CS101, CS102, MATH101, MATH201)
    code_map = {c["code"]: c["id"] for c in courses}
    foundation_codes = ["CS101", "CS102", "MATH101", "MATH201"]

    for sid in range(1, 51):
        for code in foundation_codes:
            if code in code_map:
                cid = code_map[code]
                existing_pairs.add((sid, cid))
                grades.append({
                    "student_id": sid,
                    "course_id": cid,
                    "grade": "A",
                    "grade_point": 4.0,
                    "passed": True
                })

    while len(grades) < num_grades:
        s = random.choice(students)
        c = random.choice(courses)
        pair = (s["id"], c["id"])
        if pair in existing_pairs:
            continue
        existing_pairs.add(pair)
        g_letter, g_point, passed = random.choice(grade_letter_map)
        grades.append({
            "student_id": s["id"],
            "course_id": c["id"],
            "grade": g_letter,
            "grade_point": g_point,
            "passed": passed
        })

    return grades


# ------------------------------------------------------------------------------
# Master Seeder
# ------------------------------------------------------------------------------

def run_seed(
    pg_client: Optional[PostgresClient] = None,
    mongo_client: Optional[MongoClient] = None,
    redis_client: Optional[RedisClient] = None,
    neo4j_client: Optional[Neo4jClient] = None,
    pg_vec_client: Optional[PgVectorClient] = None,
    qdrant_client: Optional[QdrantStoreClient] = None
):
    logger.info("=================================================================")
    logger.info("Starting Course Enrolment Advisor Multi-Store Seeding Pipeline")
    logger.info("=================================================================")

    # 1. Generate Synthetic Data
    logger.info("Generating realistic university curriculum, students, and sections...")
    courses, mongo_docs, prerequisites, equivalencies = generate_curriculum_catalog(total_courses=300)
    students = generate_students(num_students=500)
    sections, enrolments = generate_sections_and_enrolments(courses, students, num_sections=400)
    grades = generate_grades(students, courses, num_grades=800)

    logger.info(f"Generated: {len(courses)} Courses, {len(students)} Students, "
                f"{len(sections)} Sections, {len(enrolments)} Enrolments, {len(grades)} Grades.")

    # 2. Initialize Clients if not provided
    if pg_client is None:
        pg_client = PostgresClient()
        pg_client.connect()
    if mongo_client is None:
        mongo_client = MongoClient()
        mongo_client.connect()
    if redis_client is None:
        redis_client = RedisClient()
        redis_client.connect()
    if neo4j_client is None:
        neo4j_client = Neo4jClient()
        neo4j_client.connect()
    if pg_vec_client is None:
        pg_vec_client = PgVectorClient(postgres_client=pg_client)
    if qdrant_client is None:
        qdrant_client = QdrantStoreClient()
        qdrant_client.connect()

    # 3. Populate PostgreSQL (System of Record for Business Entities)
    logger.info("Populating PostgreSQL (System of Record)...")
    pg_client.init_schema()
    if pg_client._is_connected:
        with pg_client._pool.connection() as conn:
            with conn.cursor() as cur:
                # Clear existing
                cur.execute("TRUNCATE enrolments, grades, sections, course_embeddings, courses, students CASCADE;")
                # Insert Students
                cur.executemany(
                    "INSERT INTO students (id, name, email, matriculation_year, major) VALUES (%(id)s, %(name)s, %(email)s, %(matriculation_year)s, %(major)s);",
                    students
                )
                # Insert Courses
                cur.executemany(
                    "INSERT INTO courses (id, code, title, credits, semester, department) VALUES (%(id)s, %(code)s, %(title)s, %(credits)s, %(semester)s, %(department)s);",
                    courses
                )
                # Insert Sections
                cur.executemany(
                    "INSERT INTO sections (id, course_id, term, capacity, seats_taken) VALUES (%(id)s, %(course_id)s, %(term)s, %(capacity)s, %(seats_taken)s);",
                    sections
                )
                # Insert Enrolments
                cur.executemany(
                    "INSERT INTO enrolments (student_id, section_id, status) VALUES (%(student_id)s, %(section_id)s, %(status)s);",
                    enrolments
                )
                # Insert Grades
                cur.executemany(
                    "INSERT INTO grades (student_id, course_id, grade, grade_point, passed) VALUES (%(student_id)s, %(course_id)s, %(grade)s, %(grade_point)s, %(passed)s);",
                    grades
                )
            conn.commit()
    else:
        # Populate in-memory fallback
        for s in students:
            pg_client._mock_data["students"][s["id"]] = s
        for c in courses:
            pg_client._mock_data["courses"][c["id"]] = c
        for sec in sections:
            pg_client._mock_data["sections"][sec["id"]] = sec
        for enr in enrolments:
            pg_client._mock_data["enrolments"][enr["id"]] = enr
        for g in grades:
            pg_client._mock_data["grades"][(g["student_id"], g["course_id"])] = g

    # 4. Populate MongoDB (System of Record for Flexible Course Documents)
    logger.info("Populating MongoDB (System of Record for Course Syllabi)...")
    mongo_client.init_indexes()
    mongo_client.insert_batch(mongo_docs)

    # 5. Populate Neo4j (Derived Graph Store)
    logger.info("Synchronizing Neo4j (Derived Graph for Prerequisites & Completed Courses)...")
    neo4j_client.init_schema()
    neo4j_client.sync_course_catalog(courses, prerequisites, equivalencies)
    neo4j_client.sync_student_grades(grades)

    # 6. Generate Vector Embeddings & Synchronize Derived Vector Stores
    logger.info("Generating Normalized Vector Embeddings (sentence-transformers/all-MiniLM-L6-v2, 384-dim)...")
    descriptions = [d["description"] for d in mongo_docs]
    embeddings = generate_embeddings_batch(descriptions)

    vector_items = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for c, emb in zip(courses, embeddings):
        vector_items.append({
            "course_id": c["id"],
            "code": c["code"],
            "title": c["title"],
            "semester": c["semester"],
            "credits": c["credits"],
            "embedding": emb,
            "source_id": "mongo_courses",
            "refreshed_at": now_iso
        })

    # Synchronize pgvector
    logger.info("Populating pgvector (course_embeddings)...")
    if pg_client._is_connected:
        with pg_client._pool.connection() as conn:
            with conn.cursor() as cur:
                for item in vector_items:
                    vec_str = f"[{','.join(map(str, item['embedding']))}]"
                    cur.execute(
                        """
                        INSERT INTO course_embeddings (course_id, embedding, source_id, refreshed_at)
                        VALUES (%s, %s::vector, %s, %s)
                        ON CONFLICT (course_id) DO UPDATE SET
                            embedding = EXCLUDED.embedding,
                            refreshed_at = EXCLUDED.refreshed_at;
                        """,
                        (item["course_id"], vec_str, item["source_id"], item["refreshed_at"])
                    )
            conn.commit()
    else:
        for item in vector_items:
            pg_client._mock_data["embeddings"][item["course_id"]] = item
    pg_vec_client.set_vectors(vector_items)

    # Synchronize Qdrant
    logger.info("Populating Qdrant Collection with Payload Indexes...")
    qdrant_client.init_collection()
    qdrant_client.upsert_vectors(vector_items)

    # 7. Seed Initial Redis Sessions (Derived Cache)
    logger.info("Populating Redis (Derived Student Planned Course Sessions)...")
    for s in students[:20]:
        planned = random.sample([c["id"] for c in courses], 3)
        redis_client.save_planned_courses(s["id"], planned)

    logger.info("=================================================================")
    logger.info("All 5 Database Stores Successfully Seeded with Provenance Metadata!")
    logger.info("=================================================================")

    return (pg_client, mongo_client, redis_client, neo4j_client, pg_vec_client, qdrant_client)


if __name__ == "__main__":
    run_seed()
