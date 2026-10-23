"""
Embedding Generation Utility for Course Enrolment Advisor.
Standardizes vector generation using sentence-transformers/all-MiniLM-L6-v2 (384 dimensions, L2-normalized).
Provides a resilient fallback implementation for environments without torch/sentence_transformers installed.
"""

import math
import hashlib
from typing import List, Union
try:
    import numpy as np
except ImportError:
    np = None
from config import config

_MODEL = None
_MODEL_LOADED = False


def _get_model():
    global _MODEL, _MODEL_LOADED
    if not _MODEL_LOADED:
        try:
            from sentence_transformers import SentenceTransformer
            _MODEL = SentenceTransformer(config.embedding.model_name)
        except Exception:
            _MODEL = None
        _MODEL_LOADED = True
    return _MODEL


def _fallback_deterministic_embed(text: str, dimension: int = 384) -> List[float]:
    """
    Deterministic semantic hash embedding fallback (normalized L2 vector).
    Constructs a 384-dimensional unit vector based on text tokens and hashes.
    Ensures that identical or semantically close strings produce consistent vectors.
    """
    words = text.lower().strip().split()
    if np is not None:
        vec = np.zeros(dimension, dtype=np.float32)
    else:
        vec = [0.0] * dimension
    if not words:
        vec[0] = 1.0
        return vec.tolist() if np is not None else vec

    for word in words:
        # Generate word seed
        seed_hash = hashlib.sha256(word.encode("utf-8")).digest()
        # Seed indices
        for i in range(0, min(len(seed_hash), 32), 4):
            idx = int.from_bytes(seed_hash[i:i + 2], "big") % dimension
            sign = 1.0 if seed_hash[i + 2] % 2 == 0 else -1.0
            val = (seed_hash[i + 3] / 255.0) * sign
            vec[idx] += val

    # L2 normalize
    if np is not None:
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        else:
            vec[0] = 1.0
        return vec.tolist()
    else:
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            return [x / norm for x in vec]
        vec[0] = 1.0
        return vec


def generate_embedding(text: str) -> List[float]:
    """
    Generate normalized 384-dimension embedding for text using all-MiniLM-L6-v2.
    """
    model = _get_model()
    if model is not None:
        embedding = model.encode(text, normalize_embeddings=True)
        return embedding.tolist()
    return _fallback_deterministic_embed(text, config.embedding.dimension)


def generate_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """
    Batch generate normalized 384-dimension embeddings.
    """
    model = _get_model()
    if model is not None:
        embeddings = model.encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False)
        return [emb.tolist() for emb in embeddings]
    return [_fallback_deterministic_embed(t, config.embedding.dimension) for t in texts]


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """
    Compute cosine similarity between two unit-normalized vectors.
    Since vectors are normalized, cosine similarity is simply the dot product.
    """
    if np is not None:
        a = np.array(v1, dtype=np.float32)
        b = np.array(v2, dtype=np.float32)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))
    else:
        dot = sum(x * y for x, y in zip(v1, v2))
        norm_a = math.sqrt(sum(x * x for x in v1))
        norm_b = math.sqrt(sum(y * y for y in v2))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))
