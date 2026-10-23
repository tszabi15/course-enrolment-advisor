"""
Qdrant Store Client for Course Enrolment Advisor.
Dedicated Vector Database managing normalized MiniLM embeddings.
Supports payload indexing, exact search, and HNSW search with hnsw_ef tuning.
"""

import time
import logging
from typing import List, Dict, Any, Optional, Tuple
from config import config

logger = logging.getLogger(__name__)


class QdrantStoreClient:
    def __init__(self, host: Optional[str] = None, port: Optional[int] = None, collection: Optional[str] = None, use_mock: bool = False):
        self.host = host or config.qdrant.host
        self.port = port or config.qdrant.port
        self.collection = collection or config.qdrant.collection
        self.use_mock = use_mock
        self._client = None
        self._is_connected = False
        self._mock_points: List[Dict[str, Any]] = []

    def connect(self):
        if self.use_mock:
            self._is_connected = False
            return
        try:
            from qdrant_client import QdrantClient
            self._client = QdrantClient(host=self.host, port=self.port, timeout=3.0)
            self._client.get_collections()
            self._is_connected = True
            logger.info("Successfully connected to Qdrant vector database.")
        except Exception as e:
            logger.warning(f"Qdrant live connection unavailable ({e}). Using in-memory fallback simulation.")
            self._is_connected = False

    def init_collection(self):
        """
        Creates collection with Cosine distance and payload index on filtered fields (semester, credits).
        """
        if self._is_connected:
            from qdrant_client.http import models
            # Recreate or create collection
            collections = [c.name for c in self._client.get_collections().collections]
            if self.collection not in collections:
                self._client.create_collection(
                    collection_name=self.collection,
                    vectors_config=models.VectorParams(
                        size=config.embedding.dimension,
                        distance=models.Distance.COSINE
                    ),
                    hnsw_config=models.HnswConfigDiff(m=16, ef_construct=64)
                )
                # Create payload index on semester (keyword) and credits (integer)
                self._client.create_payload_index(
                    collection_name=self.collection,
                    field_name="semester",
                    field_schema=models.PayloadSchemaType.KEYWORD
                )
                self._client.create_payload_index(
                    collection_name=self.collection,
                    field_name="credits",
                    field_schema=models.PayloadSchemaType.INTEGER
                )

    def upsert_vectors(self, vectors: List[Dict[str, Any]]):
        """
        Upserts normalized vectors and payload into Qdrant.
        """
        if self._is_connected:
            from qdrant_client.http import models
            points = [
                models.PointStruct(
                    id=v["course_id"],
                    vector=v["embedding"],
                    payload={
                        "course_id": v["course_id"],
                        "code": v["code"],
                        "title": v["title"],
                        "semester": v["semester"],
                        "credits": v["credits"],
                        "source_id": "mongo_courses",
                        "refreshed_at": v.get("refreshed_at", "")
                    }
                )
                for v in vectors
            ]
            self._client.upsert(collection_name=self.collection, points=points)
        else:
            self._mock_points = vectors

    def search_exact(self, query_vector: List[float], limit: int = 10, semester: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Exact (brute-force) top-K search in Qdrant with exact=True.
        """
        if self._is_connected:
            from qdrant_client.http import models
            query_filter = None
            if semester:
                query_filter = models.Filter(
                    must=[models.FieldCondition(key="semester", match=models.MatchValue(value=semester))]
                )
            search_params = models.SearchParams(exact=True)
            if hasattr(self._client, "search"):
                points = self._client.search(
                    collection_name=self.collection,
                    query_vector=query_vector,
                    query_filter=query_filter,
                    limit=limit,
                    search_params=search_params
                )
            else:
                resp = self._client.query_points(
                    collection_name=self.collection,
                    query=query_vector,
                    query_filter=query_filter,
                    limit=limit,
                    search_params=search_params
                )
                points = resp.points

            return [
                {
                    "course_id": r.payload["course_id"],
                    "code": r.payload["code"],
                    "title": r.payload["title"],
                    "credits": r.payload["credits"],
                    "semester": r.payload["semester"],
                    "score": float(r.score)
                }
                for r in points
            ]
        else:
            from src.embeddings import cosine_similarity
            items = []
            for item in self._mock_points:
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
        hnsw_ef: int = 40
    ) -> Tuple[List[Dict[str, Any]], float]:
        """
        HNSW Approximate Nearest Neighbor search with configurable hnsw_ef.
        Returns: (results, latency_ms)
        """
        start_time = time.perf_counter()
        if self._is_connected:
            from qdrant_client.http import models
            query_filter = None
            if semester:
                query_filter = models.Filter(
                    must=[models.FieldCondition(key="semester", match=models.MatchValue(value=semester))]
                )
            search_params = models.SearchParams(hnsw_ef=hnsw_ef, exact=False)
            if hasattr(self._client, "search"):
                points = self._client.search(
                    collection_name=self.collection,
                    query_vector=query_vector,
                    query_filter=query_filter,
                    limit=limit,
                    search_params=search_params
                )
            else:
                resp = self._client.query_points(
                    collection_name=self.collection,
                    query=query_vector,
                    query_filter=query_filter,
                    limit=limit,
                    search_params=search_params
                )
                points = resp.points

            res = [
                {
                    "course_id": r.payload["course_id"],
                    "code": r.payload["code"],
                    "title": r.payload["title"],
                    "credits": r.payload["credits"],
                    "semester": r.payload["semester"],
                    "score": float(r.score)
                }
                for r in points
            ]
        else:
            exact = self.search_exact(query_vector, limit=limit, semester=semester)
            res = exact

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        return res, latency_ms

    def two_step_vector_business_query(self, query_vector: List[float], semester: str, postgres_client, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Required Query: Equivalent query using Qdrant.
        Step 1: Vector search in Qdrant with semester filter.
        Step 2: Relational query to PostgreSQL to check seat availability for the candidate courses.
        """
        # Step 1: Candidate retrieval via Qdrant
        qdrant_candidates, _ = self.search_hnsw(query_vector=query_vector, limit=limit * 2, semester=semester)

        if not qdrant_candidates:
            return []

        candidate_ids = [c["course_id"] for c in qdrant_candidates]
        candidate_scores = {c["course_id"]: c["score"] for c in qdrant_candidates}

        # Step 2: Query relational store (Postgres) for remaining seats
        final_results = []
        if postgres_client and postgres_client._is_connected:
            with postgres_client._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT s.course_id, s.id AS section_id, (s.capacity - s.seats_taken) AS seats_remaining,
                               c.code, c.title, c.credits, c.semester
                        FROM sections s
                        JOIN courses c ON s.course_id = c.id
                        WHERE s.course_id = ANY(%s) AND s.seats_taken < s.capacity;
                        """,
                        (candidate_ids,)
                    )
                    rows = cur.fetchall()
                    for r in rows:
                        c_id = r[0]
                        final_results.append({
                            "course_id": c_id,
                            "code": r[3],
                            "title": r[4],
                            "credits": r[5],
                            "semester": r[6],
                            "section_id": r[1],
                            "seats_remaining": r[2],
                            "similarity_score": candidate_scores.get(c_id, 0.0)
                        })
        else:
            # Fallback using postgres client internal state
            for c_id in candidate_ids:
                course = postgres_client._mock_data["courses"].get(c_id)
                if not course or course["semester"] != semester:
                    continue
                open_sections = [
                    s for s in postgres_client._mock_data["sections"].values()
                    if s["course_id"] == c_id and s["seats_taken"] < s["capacity"]
                ]
                if open_sections:
                    sec = open_sections[0]
                    final_results.append({
                        "course_id": c_id,
                        "code": course["code"],
                        "title": course["title"],
                        "credits": course["credits"],
                        "semester": course["semester"],
                        "section_id": sec["id"],
                        "seats_remaining": sec["capacity"] - sec["seats_taken"],
                        "similarity_score": candidate_scores.get(c_id, 0.0)
                    })

        final_results.sort(key=lambda x: x["similarity_score"], reverse=True)
        return final_results[:limit]
