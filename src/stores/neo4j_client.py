"""
Neo4j Graph Store Client for Course Enrolment Advisor.
Derived graph holding prerequisites, course equivalencies, and completed student grades.
Answers graph-native queries:
1. Find courses whose prerequisites a student has completed.
2. Calculate shortest prerequisite path to a designated target course.
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from config import config

logger = logging.getLogger(__name__)


class Neo4jClient:
    def __init__(self, uri: Optional[str] = None, user: Optional[str] = None, password: Optional[str] = None):
        self.uri = uri or config.neo4j.uri
        self.user = user or config.neo4j.user
        self.password = password or config.neo4j.password
        self._driver = None
        self._is_connected = False
        # In-memory graph fallback
        self._mock_courses: Dict[int, Dict[str, Any]] = {}
        self._mock_prereqs: List[Dict[str, Any]] = []  # course_id requires prereq_id
        self._mock_equivalences: List[Tuple[int, int]] = []
        self._mock_completed: List[Dict[str, Any]] = []

    def connect(self):
        try:
            from neo4j import GraphDatabase
            self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            with self._driver.session() as session:
                session.run("RETURN 1;")
            self._is_connected = True
            logger.info("Successfully connected to Neo4j graph database.")
        except Exception as e:
            logger.warning(f"Neo4j live connection unavailable ({e}). Using in-memory fallback simulation.")
            self._is_connected = False

    def init_schema(self):
        if self._is_connected:
            with self._driver.session() as session:
                session.run("CREATE CONSTRAINT course_id_unique IF NOT EXISTS FOR (c:Course) REQUIRE c.id IS UNIQUE;")
                session.run("CREATE CONSTRAINT student_id_unique IF NOT EXISTS FOR (s:Student) REQUIRE s.id IS UNIQUE;")

    def sync_course_catalog(self, courses: List[Dict[str, Any]], prerequisites: List[Dict[str, Any]], equivalencies: Optional[List[Dict[str, Any]]] = None):
        """
        Populate Course nodes, REQUIRES (prerequisite) edges, and EQUIVALENT_TO edges.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        if self._is_connected:
            with self._driver.session() as session:
                # Merge Courses
                session.run(
                    """
                    UNWIND $courses AS c
                    MERGE (course:Course {id: c.id})
                    SET course.code = c.code,
                        course.title = c.title,
                        course.credits = c.credits,
                        course.semester = c.semester,
                        course.source_id = 'postgres_courses',
                        course.refreshed_at = $refreshed_at;
                    """,
                    courses=courses, refreshed_at=now_iso
                )
                # Merge Prerequisites: (c:Course)-[:REQUIRES]->(p:Course)
                session.run(
                    """
                    UNWIND $prereqs AS p
                    MATCH (c:Course {id: p.course_id})
                    MATCH (prereq:Course {id: p.prerequisite_id})
                    MERGE (c)-[r:REQUIRES]->(prereq)
                    SET r.source_id = 'postgres_catalog',
                        r.refreshed_at = $refreshed_at;
                    """,
                    prereqs=prerequisites, refreshed_at=now_iso
                )
                # Merge Equivalencies: (c1:Course)-[:EQUIVALENT_TO]-(c2:Course)
                if equivalencies:
                    session.run(
                        """
                        UNWIND $eqs AS eq
                        MATCH (c1:Course {id: eq.course_id_1})
                        MATCH (c2:Course {id: eq.course_id_2})
                        MERGE (c1)-[r:EQUIVALENT_TO]->(c2)
                        SET r.source_id = 'postgres_catalog',
                            r.refreshed_at = $refreshed_at;
                        """,
                        eqs=equivalencies, refreshed_at=now_iso
                    )
        else:
            for c in courses:
                self._mock_courses[c["id"]] = c
            self._mock_prereqs = list(prerequisites)
            if equivalencies:
                self._mock_equivalences = [(e["course_id_1"], e["course_id_2"]) for e in equivalencies]

    def sync_student_grades(self, grades: List[Dict[str, Any]]):
        """
        Derived graph sync: Copy (:Student)-[:COMPLETED]->(:Course) from PostgreSQL recorded grades.
        Keeps source ID ('postgres_grades') and refreshed_at timestamp.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        passed_grades = [g for g in grades if g.get("passed", True)]

        if self._is_connected:
            with self._driver.session() as session:
                session.run(
                    """
                    UNWIND $grades AS g
                    MERGE (s:Student {id: g.student_id})
                    MERGE (c:Course {id: g.course_id})
                    MERGE (s)-[r:COMPLETED]->(c)
                    SET r.grade = g.grade,
                        r.grade_point = g.grade_point,
                        r.source_id = 'postgres_grades',
                        r.refreshed_at = $refreshed_at;
                    """,
                    grades=passed_grades, refreshed_at=now_iso
                )
        else:
            self._mock_completed = [
                {
                    "student_id": g["student_id"],
                    "course_id": g["course_id"],
                    "grade": g.get("grade", "A"),
                    "refreshed_at": now_iso,
                    "source_id": "postgres_grades"
                }
                for g in passed_grades
            ]

    def find_courses_with_completed_prerequisites(self, student_id: int) -> List[Dict[str, Any]]:
        """
        Required Query 1: Find courses whose prerequisites the student has completed,
        and which the student has not yet taken.
        Accounts for direct prerequisite completion and course equivalencies.
        """
        if self._is_connected:
            cypher = """
            MATCH (target:Course)
            WHERE NOT EXISTS {
                MATCH (:Student {id: $student_id})-[:COMPLETED]->(target)
            }
            AND ALL(prereq IN [(target)-[:REQUIRES]->(p:Course) | p] WHERE
                EXISTS {
                    MATCH (:Student {id: $student_id})-[:COMPLETED]->(prereq)
                }
                OR EXISTS {
                    MATCH (:Student {id: $student_id})-[:COMPLETED]->(:Course)-[:EQUIVALENT_TO]-(prereq)
                }
            )
            OPTIONAL MATCH (target)-[:REQUIRES]->(p:Course)
            RETURN target.id AS course_id, 
                   target.code AS code, 
                   target.title AS title, 
                   target.credits AS credits, 
                   target.semester AS semester,
                   collect(p.code) AS fulfilled_prerequisites
            ORDER BY target.code;
            """
            with self._driver.session() as session:
                result = session.run(cypher, student_id=student_id)
                return [
                    {
                        "course_id": record["course_id"],
                        "code": record["code"],
                        "title": record["title"],
                        "credits": record["credits"],
                        "semester": record["semester"],
                        "fulfilled_prerequisites": record["fulfilled_prerequisites"]
                    }
                    for record in result
                ]
        else:
            # Graph algorithm simulation
            completed_ids = set()
            for rec in self._mock_completed:
                if rec["student_id"] == student_id:
                    completed_ids.add(rec["course_id"])
                    # Add equivalent courses
                    for c1, c2 in self._mock_equivalences:
                        if rec["course_id"] == c1:
                            completed_ids.add(c2)
                        elif rec["course_id"] == c2:
                            completed_ids.add(c1)

            results = []
            for c_id, course in self._mock_courses.items():
                if c_id in completed_ids:
                    continue  # Already taken
                # Get all prerequisites
                reqs = [p["prerequisite_id"] for p in self._mock_prereqs if p["course_id"] == c_id]
                # Check if all reqs are in completed_ids
                if all(req_id in completed_ids for req_id in reqs):
                    req_codes = [self._mock_courses[r]["code"] for r in reqs if r in self._mock_courses]
                    results.append({
                        "course_id": c_id,
                        "code": course["code"],
                        "title": course["title"],
                        "credits": course["credits"],
                        "semester": course["semester"],
                        "fulfilled_prerequisites": req_codes
                    })
            results.sort(key=lambda x: x["code"])
            return results

    def find_shortest_prerequisite_path(self, start_course_code: str, target_course_code: str) -> Dict[str, Any]:
        """
        Required Query 2: Calculate the shortest prerequisite path to a designated target course.
        Returns the sequence of courses, path length, and prerequisite dependencies.
        """
        if self._is_connected:
            cypher = """
            MATCH (start:Course {code: $start_code}), (target:Course {code: $target_code})
            MATCH p = shortestPath((target)-[:REQUIRES*1..10]->(start))
            RETURN [n IN nodes(p) | {id: n.id, code: n.code, title: n.title}] AS path_nodes,
                   length(p) AS path_length;
            """
            with self._driver.session() as session:
                res = session.run(cypher, start_code=start_course_code, target_code=target_course_code)
                record = res.single()
                if record:
                    # Invert because path goes target -> ... -> start
                    nodes = list(reversed(record["path_nodes"]))
                    return {
                        "found": True,
                        "path": nodes,
                        "path_length": record["path_length"],
                        "start_code": start_course_code,
                        "target_code": target_course_code
                    }
                return {"found": False, "path": [], "path_length": -1}
        else:
            # BFS on in-memory adjacency list
            code_to_id = {c["code"]: c_id for c_id, c in self._mock_courses.items()}
            if start_course_code not in code_to_id or target_course_code not in code_to_id:
                return {"found": False, "path": [], "path_length": -1}

            start_id = code_to_id[start_course_code]
            target_id = code_to_id[target_course_code]

            # We want path from start -> target where (dependent)-[:REQUIRES]->(prereq)
            # which is an edge prereq -> dependent
            adj: Dict[int, List[int]] = {}
            for p in self._mock_prereqs:
                prereq = p["prerequisite_id"]
                dep = p["course_id"]
                adj.setdefault(prereq, []).append(dep)

            from collections import deque
            queue = deque([[start_id]])
            visited = {start_id}

            while queue:
                path = queue.popleft()
                curr = path[-1]
                if curr == target_id:
                    path_nodes = [
                        {"id": nid, "code": self._mock_courses[nid]["code"], "title": self._mock_courses[nid]["title"]}
                        for nid in path
                    ]
                    return {
                        "found": True,
                        "path": path_nodes,
                        "path_length": len(path) - 1,
                        "start_code": start_course_code,
                        "target_code": target_course_code
                    }
                for neighbor in adj.get(curr, []):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(path + [neighbor])

            return {"found": False, "path": [], "path_length": -1}

    def close(self):
        if self._driver:
            self._driver.close()
            self._driver = None
            self._is_connected = False
