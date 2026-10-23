"""
Centralized Configuration for Course Enrolment Advisor.
Loads configuration from environment variables or .env file with sensible defaults.
"""

import os
from dataclasses import dataclass
from typing import Optional
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass(frozen=True)
class PostgresConfig:
    host: str = os.getenv("POSTGRES_HOST", "localhost")
    port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    db: str = os.getenv("POSTGRES_DB", "advisor_db")
    user: str = os.getenv("POSTGRES_USER", "advisor_user")
    password: str = os.getenv("POSTGRES_PASSWORD", "advisor_password")
    sslmode: str = os.getenv("POSTGRES_SSLMODE", "disable")

    @property
    def dsn(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}?sslmode={self.sslmode}"


@dataclass(frozen=True)
class MongoConfig:
    host: str = os.getenv("MONGO_HOST", "localhost")
    port: int = int(os.getenv("MONGO_PORT", "27017"))
    db: str = os.getenv("MONGO_DB", "advisor_catalog")
    user: str = os.getenv("MONGO_USER", "advisor_admin")
    password: str = os.getenv("MONGO_PASSWORD", "advisor_secret")
    auth_source: str = os.getenv("MONGO_AUTH_SOURCE", "admin")

    @property
    def uri(self) -> str:
        if self.user and self.password:
            return f"mongodb://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}?authSource={self.auth_source}"
        return f"mongodb://{self.host}:{self.port}/{self.db}"


@dataclass(frozen=True)
class RedisConfig:
    host: str = os.getenv("REDIS_HOST", "localhost")
    port: int = int(os.getenv("REDIS_PORT", "6379"))
    password: Optional[str] = os.getenv("REDIS_PASSWORD", None) or None
    db: int = int(os.getenv("REDIS_DB", "0"))
    session_ttl: int = int(os.getenv("REDIS_SESSION_TTL_SECONDS", "1800"))


@dataclass(frozen=True)
class Neo4jConfig:
    host: str = os.getenv("NEO4J_HOST", "localhost")
    port: int = int(os.getenv("NEO4J_PORT", "7687"))
    user: str = os.getenv("NEO4J_USER", "neo4j")
    password: str = os.getenv("NEO4J_PASSWORD", "advisor_neo4j_password")

    @property
    def uri(self) -> str:
        return f"bolt://{self.host}:{self.port}"


@dataclass(frozen=True)
class QdrantConfig:
    host: str = os.getenv("QDRANT_HOST", "localhost")
    port: int = int(os.getenv("QDRANT_PORT", "6333"))
    grpc_port: int = int(os.getenv("QDRANT_GRPC_PORT", "6334"))
    collection: str = os.getenv("QDRANT_COLLECTION", "course_embeddings")


@dataclass(frozen=True)
class EmbeddingConfig:
    model_name: str = os.getenv("EMBEDDING_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2")
    dimension: int = int(os.getenv("EMBEDDING_DIMENSION", "384"))
    metric: str = os.getenv("EMBEDDING_DISTANCE", "Cosine")


@dataclass(frozen=True)
class AppConfig:
    postgres: PostgresConfig = PostgresConfig()
    mongo: MongoConfig = MongoConfig()
    redis: RedisConfig = RedisConfig()
    neo4j: Neo4jConfig = Neo4jConfig()
    qdrant: QdrantConfig = QdrantConfig()
    embedding: EmbeddingConfig = EmbeddingConfig()


config = AppConfig()
