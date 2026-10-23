# Course Enrolment Advisor (Project 3)

A polyglot university decision and advising system built across five database paradigms: **PostgreSQL** (relational + pgvector), **MongoDB** (document), **Redis** (key-value), **Neo4j** (graph), and **Qdrant** (dedicated vector engine).

The system decides whether a student is eligible to enrol in a course (combining relational seat quotas and graph prerequisite traversal) and suggests courses matching student free-text interests.

---

## 1. Architectural Role & Storage Rationale (One Reason Per Store)

| Store | Paradigm | Role | Core Reason for Storage Selection |
| :--- | :--- | :--- | :--- |
| **PostgreSQL** | Relational | **System of Record** | Enforces ACID guarantees, row-level locking (`SELECT ... FOR UPDATE`), and relational constraints (`CHECK (seats_taken <= capacity)`, `UNIQUE (student_id, section_id)`) to prevent seat over-subscription and race conditions. |
| **MongoDB** | Document | **System of Record** | Accommodates polymorphic, semi-structured course syllabi, lab protocols, varying grading rubrics, and reading lists without schema friction. |
| **Redis** | Key-Value | **Derived Cache** | Stores interactive student planned course sessions with TTLs to offload relational traffic, survive page reloads, and expire after inactivity. |
| **Neo4j** | Graph | **Derived Graph Store** | Models prerequisite dependency DAGs, course equivalencies, and completed student grades to execute multi-hop prerequisite verification and shortest path queries. |
| **pgvector & Qdrant** | Vector | **Derived Vector Stores** | Store 384-dimensional normalized MiniLM embeddings (`all-MiniLM-L6-v2`) of course descriptions with semester/credit metadata. pgvector enables single-statement transactional joins with seat tables; Qdrant provides high-throughput filtered vector search. |

---

## 2. Git Workflow & Branching Strategy

The repository follows a structured feature-branch workflow with conventional commits:

```text
main
  │
  ├── feature/docker-setup          (Docker Compose, healthchecks, configs)
  ├── feature/data-seed             (200–1,000 realistic records per store with provenance)
  ├── feature/pg-mongo-queries      (ACID locking, MongoDB lab+exam query, Redis session)
  ├── feature/graph-traversal       (Neo4j completed prerequisites & shortest path)
  ├── feature/vector-benchmarks     (pgvector vs. Qdrant HNSW/Exact, Recall@5, MRR, 5% filter)
  └── feature/cross-store-update    (PostgreSQL mutation -> eventual consistency audit)
```

---

## 3. Quickstart & Execution Guide

### Step 1: Start Infrastructure via Docker Compose
```bash
docker compose up -d
```
All five containers include configured health checks, persistent volumes, and port mappings:
- PostgreSQL (pgvector): `localhost:5432`
- MongoDB: `localhost:27017`
- Redis: `localhost:6379`
- Neo4j: `localhost:7474` (HTTP) / `localhost:7687` (Bolt)
- Qdrant: `localhost:6333` (REST) / `localhost:6334` (gRPC)

### Step 2: Install Python Dependencies
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Step 3: Seed All 5 Stores with Realistic Data
Generates 300 courses, 500 students, 400 sections, 800 grades, and 300 vector embeddings:
```bash
python seed_data.py
```

### Step 4: Run the Cross-Store Eventual Consistency Demonstration
Mutates a source grade in PostgreSQL, proves stale state in derived stores, triggers synchronization, and verifies freshness:
```bash
python cross_store_update.py
```

### Step 5: Execute the Full Evaluation & Benchmark Suite
Runs the 15 eligibility test cases, 20 labelled interest queries, HNSW vs. Exact ANN recall comparisons, 5% filter selectivity benchmark, and outputs `benchmark_results.md`:
```bash
python run_benchmarks.py
```

### Step 6: Run Automated Tests
```bash
pytest tests/ -v
```

---

## 4. Key Queries Implemented

### 1. PostgreSQL ACID Enrolment Locking & Concurrency
```sql
BEGIN;
SELECT capacity, seats_taken FROM sections WHERE id = $section_id FOR UPDATE;
-- Check seats_taken < capacity
INSERT INTO enrolments (student_id, section_id, status) VALUES ($student_id, $section_id, 'ENROLLED');
UPDATE sections SET seats_taken = seats_taken + 1 WHERE id = $section_id;
COMMIT;
```

### 2. MongoDB Lab and Exam Query
```javascript
db.courses.find(
  { "has_lab": true, "has_exam": true },
  { course_id: 1, code: 1, title: 1, grading_rubric: 1 }
);
```

### 3. Neo4j Prerequisite Completion Query
```cypher
MATCH (target:Course)
WHERE NOT EXISTS { MATCH (:Student {id: $student_id})-[:COMPLETED]->(target) }
AND ALL(prereq IN [(target)-[:REQUIRES]->(p:Course) | p] WHERE
    EXISTS { MATCH (:Student {id: $student_id})-[:COMPLETED]->(prereq) }
    OR EXISTS { MATCH (:Student {id: $student_id})-[:COMPLETED]->(:Course)-[:EQUIVALENT_TO]-(prereq) }
)
RETURN target.code, target.title;
```

### 4. pgvector Integrated Single SQL Query
```sql
SELECT c.id, c.code, c.title, c.credits, s.id AS section_id,
       (s.capacity - s.seats_taken) AS seats_remaining,
       (1 - (e.embedding <=> %(query_vector)s::vector)) AS similarity
FROM course_embeddings e
JOIN courses c ON e.course_id = c.id
JOIN sections s ON s.course_id = c.id
WHERE s.seats_taken < s.capacity AND c.semester = %(semester)s
ORDER BY e.embedding <=> %(query_vector)s::vector
LIMIT 5;
```

---

## 5. Failure / Edge Case Analysis

1. **Concurrent Last-Seat Over-Subscription**: Prevented through relational serialization via `SELECT ... FOR UPDATE` and database-level `CHECK (seats_taken <= capacity)`. In our concurrency benchmark, two competing threads attempted to book the 1 remaining seat: Thread 1 committed and Thread 2 was rejected cleanly with a `SeatFullError`.
2. **HNSW Filter Recall Degradation Under Tight Selectivity (~5%)**: High-selectivity post-filtering in HNSW graphs degrades ANN recall. In **pgvector**, enabling `hnsw.iterative_scan = 'relaxed'` or increasing `ef_search` recovers recall. In **Qdrant**, creating a payload index on `semester` integrates filtering directly into index navigation.
