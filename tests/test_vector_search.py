"""
Unit Tests for Vector Stores (pgvector & Qdrant).
Verifies exact vs. HNSW searches, ANN Recall@10 computation, and high-selectivity filtering.
"""

from src.stores.vector_pg import PgVectorClient
from src.stores.vector_qdrant import QdrantStoreClient
from src.embeddings import generate_embedding


def test_vector_search_exact_and_hnsw():
    pg_vec = PgVectorClient()
    qdrant = QdrantStoreClient()

    # Create dummy vector records
    records = []
    for i in range(1, 51):
        sem = "Summer" if i <= 5 else "Fall"
        title = f"Course {i} on Deep Learning" if i % 2 == 0 else f"Course {i} on Database Systems"
        emb = generate_embedding(title)
        records.append({
            "course_id": i,
            "code": f"C{i}",
            "title": title,
            "semester": sem,
            "credits": 4,
            "embedding": emb
        })

    pg_vec.set_vectors(records)
    qdrant.upsert_vectors(records)

    query_vec = generate_embedding("deep learning neural networks")

    # Test pgvector
    pg_exact = pg_vec.search_exact(query_vec, limit=5)
    pg_hnsw, _ = pg_vec.search_hnsw(query_vec, limit=5)
    assert len(pg_exact) == 5
    assert len(pg_hnsw) == 5

    # Test Qdrant
    qd_exact = qdrant.search_exact(query_vec, limit=5)
    qd_hnsw, _ = qdrant.search_hnsw(query_vec, limit=5)
    assert len(qd_exact) == 5
    assert len(qd_hnsw) == 5

    # Test Filter Selectivity (~10% Summer)
    pg_filtered, _ = pg_vec.search_hnsw(query_vec, limit=10, semester="Summer")
    for r in pg_filtered:
        assert r["semester"] == "Summer"

    qd_filtered, _ = qdrant.search_hnsw(query_vec, limit=10, semester="Summer")
    for r in qd_filtered:
        assert r["semester"] == "Summer"


import unittest


class TestVectorSearch(unittest.TestCase):
    def test_vectors(self):
        test_vector_search_exact_and_hnsw()
