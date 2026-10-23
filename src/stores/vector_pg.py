"""
pgvector Store Client for Course Enrolment Advisor.
Implements exact flat search and HNSW approximate nearest neighbor search (cosine distance).
Supports tuning hnsw.ef_search and hnsw.iterative_scan for filtered vector searches.
"""

import time
import logging
from typing import List, Dict, Any, Optional
from config import config

logger = logging.getLogger(__name__)


class PgVectorClient:
    def __init__(self, postgres_client=None):
        self.pg = postgres_client
        self._mock_vectors: List[Dict[str, Any]] = []

    def set_vectors(self, vectors: List[Dict[str, Any]]):
        """Used for seeding / fallback."""
        self._mock_vectors = vectors

    def search_exact(self, query_vector: List[float], limit: int = 10, semester: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Exact (brute-force) top-K search in pgvector using sequential scan.
        """
        if self.pg and self.pg._is_connected:
            vector_str = f"[{','.join(map(str, query_vector))}]"
            with self.pg._pool.connection() as conn:
                with conn.cursor() as cur:
                    # Force sequential scan / disable HNSW index scan for ground truth
                    cur.execute("SET LOCAL enable_indexscan = off;")
                    cur.execute("SET LOCAL enable_bitmapscan = off;")
                    if semester:
                        sql = """
                        SELECT e.course_id, c.code, c.title, c.credits, c.semester,
                               (1 - (e.embedding <=> %s::vector)) AS score
                        FROM course_embeddings e
                        JOIN courses c ON e.course_id = c.id
                        WHERE c.semester = %s
                        ORDER BY e.embedding <=> %s::vector
                        LIMIT %s;
                        """
                        cur.execute(sql, (vector_str, semester, vector_str, limit))
                    else:
                        sql = """
                        SELECT e.course_id, c.code, c.title, c.credits, c.semester,
                               (1 - (e.embedding <=> %s::vector)) AS score
                        FROM course_embeddings e
                        JOIN courses c ON e.course_id = c.id
                        ORDER BY e.embedding <=> %s::vector
                        LIMIT %s;
                        """
                        cur.execute(sql, (vector_str, vector_str, limit))
                    rows = cur.fetchall()
                    return [
                        {"course_id": r[0], "code": r[1], "title": r[2], "credits": r[3], "semester": r[4], "score": float(r[5])}
                        for r in rows
                    ]
        else:
            from src.embeddings import cosine_similarity
            items = []
            for item in self._mock_vectors:
                if semester and item["semester"] != semester:
                    continue
                score = cosine_similarity(query_vector, item["embedding"])
                items.append({
                    "course_id": item["course_id"],
                    "code": item["code"],
                    "title": item["title"],
                    "credits": item["credits"],
                    "semester": item["semester"],
                    "score": score
                })
            items.sort(key=lambda x: x["score"], reverse=True)
            return items[:limit]

    def search_hnsw(
        self,
        query_vector: List[float],
        limit: int = 10,
        semester: Optional[str] = None,
        ef_search: int = 40,
        iterative_scan: str = "relaxed"
    ) -> Tuple[List[Dict[str, Any]], float]:
        """
        Approximate Nearest Neighbor search using pgvector HNSW index.
        Returns: (results, latency_ms)
        """
        start_time = time.perf_counter()
        if self.pg and self.pg._is_connected:
            vector_str = f"[{','.join(map(str, query_vector))}]"
            with self.pg._pool.connection() as conn:
                with conn.cursor() as cur:
                    # Enable index scan and configure HNSW parameters
                    cur.execute("SET LOCAL enable_indexscan = on;")
                    cur.execute(f"SET LOCAL hnsw.ef_search = {ef_search};")
                    try:
                        cur.execute(f"SET LOCAL hnsw.iterative_scan = '{iterative_scan}';")
                    except Exception:
                        pass  # Postgres version compatibility

                    if semester:
                        sql = """
                        SELECT e.course_id, c.code, c.title, c.credits, c.semester,
                               (1 - (e.embedding <=> %s::vector)) AS score
                        FROM course_embeddings e
                        JOIN courses c ON e.course_id = c.id
                        WHERE c.semester = %s
                        ORDER BY e.embedding <=> %s::vector
                        LIMIT %s;
                        """
                        cur.execute(sql, (vector_str, semester, vector_str, limit))
                    else:
                        sql = """
                        SELECT e.course_id, c.code, c.title, c.credits, c.semester,
                               (1 - (e.embedding <=> %s::vector)) AS score
                        FROM course_embeddings e
                        JOIN courses c ON e.course_id = c.id
                        ORDER BY e.embedding <=> %s::vector
                        LIMIT %s;
                        """
                        cur.execute(sql, (vector_str, vector_str, limit))
                    rows = cur.fetchall()
                    res = [
                        {"course_id": r[0], "code": r[1], "title": r[2], "credits": r[3], "semester": r[4], "score": float(r[5])}
                        for r in rows
                    ]
        else:
            # Simulated HNSW search
            exact = self.search_exact(query_vector, limit=limit, semester=semester)
            res = exact

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        return res, latency_ms
