"""
Domain Models and Data Transfer Objects for Course Enrolment Advisor.
Tracks entities, schemas, and data provenance across relational, document,
key-value, graph, and vector stores.
"""

from datetime import datetime, timezone
try:
    from pydantic import BaseModel, Field
except ImportError:
    from dataclasses import dataclass, field
    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
        def dict(self):
            return self.__dict__
    def Field(default_factory=None, default=None):
        return default_factory() if default_factory else default


# ------------------------------------------------------------------------------
# System of Record: PostgreSQL Models
# ------------------------------------------------------------------------------

class Student(BaseModel):
    id: int
    name: str
    email: str
    matriculation_year: int
    major: str


class Course(BaseModel):
    id: int
    code: str
    title: str
    credits: int
    semester: str  # e.g., "Fall", "Spring", "Summer"
    department: str


class Section(BaseModel):
    id: int
    course_id: int
    term: str  # e.g., "2026-Fall"
    capacity: int
    seats_taken: int = 0

    @property
    def seats_remaining(self) -> int:
        return max(0, self.capacity - self.seats_taken)


class Enrolment(BaseModel):
    id: Optional[int] = None
    student_id: int
    section_id: int
    status: str = "ENROLLED"  # "ENROLLED", "DROPPED"
    enrolled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GradeRecord(BaseModel):
    id: Optional[int] = None
    student_id: int
    course_id: int
    grade: str  # "A", "B", "C", "D", "F"
    grade_point: float
    passed: bool


# ------------------------------------------------------------------------------
# System of Record: MongoDB Models (Flexible Syllabi & Course Details)
# ------------------------------------------------------------------------------

class GradingRubric(BaseModel):
    exam: Optional[int] = None
    lab: Optional[int] = None
    project: Optional[int] = None
    assignments: Optional[int] = None
    participation: Optional[int] = None


class MongoCourseDocument(BaseModel):
    course_id: int
    code: str
    title: str
    description: str
    has_lab: bool = False
    has_exam: bool = True
    has_project: bool = False
    reading_list: List[str] = Field(default_factory=list)
    prerequisites_text: Optional[str] = None
    grading_rubric: Optional[Dict[str, int]] = None
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ------------------------------------------------------------------------------
# Derived Store: Redis Models (Student Planned Courses Session)
# ------------------------------------------------------------------------------

class PlannedCoursesSession(BaseModel):
    student_id: int
    planned_course_ids: List[int]
    source_id: str  # e.g., "student:101"
    refreshed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    notes: Optional[str] = None


# ------------------------------------------------------------------------------
# Derived Store: Neo4j Models (Prerequisites, Equivalencies, Graph)
# ------------------------------------------------------------------------------

class CoursePrerequisite(BaseModel):
    course_id: int
    prerequisite_course_id: int
    is_mandatory: bool = True
    source_id: str = "postgres_courses"
    refreshed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CourseEquivalence(BaseModel):
    course_id: int
    equivalent_course_id: int
    source_id: str = "postgres_courses"
    refreshed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class StudentCompletedCourse(BaseModel):
    student_id: int
    course_id: int
    grade: str
    passed: bool
    source_id: str = "postgres_grades"
    refreshed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ------------------------------------------------------------------------------
# Derived Store: Vector Models (pgvector & Qdrant)
# ------------------------------------------------------------------------------

class VectorCoursePayload(BaseModel):
    course_id: int
    code: str
    title: str
    semester: str
    credits: int
    source_id: str = "mongo_courses"
    refreshed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    description: str


class VectorSearchResult(BaseModel):
    course_id: int
    code: str
    title: str
    semester: str
    credits: int
    score: float  # Cosine similarity score
    rank: int
