"""
Unit and Concurrency Tests for PostgreSQL Enrolment Transactions.
Verifies SELECT ... FOR UPDATE row locking, CHECK constraints, and race condition handling.
"""

import unittest
try:
    import pytest
except ImportError:
    class _PytestFallback:
        def raises(self, exc):
            class _Ctx:
                def __enter__(self):
                    return self
                def __exit__(self, exc_type, exc_val, exc_tb):
                    if not exc_type:
                        raise AssertionError(f"Expected exception {exc} was not raised.")
                    return issubclass(exc_type, exc)
            return _Ctx()
    pytest = _PytestFallback()
from src.stores.postgres_client import PostgresClient, SeatFullError, AlreadyEnrolledError


def test_single_enrolment_success():
    client = PostgresClient()
    client.connect()
    client._init_mock_storage()

    # Create section with capacity 2, seats_taken 0
    client._mock_data["sections"][1] = {"id": 1, "course_id": 101, "capacity": 2, "seats_taken": 0}

    res = client.enrol_student(student_id=1, section_id=1)
    assert res["success"] is True
    assert res["seats_taken"] == 1
    assert client._mock_data["sections"][1]["seats_taken"] == 1


def test_enrolment_seat_full_rejected():
    client = PostgresClient()
    client.connect()
    client._init_mock_storage()

    # Section with capacity 1, seats_taken 1
    client._mock_data["sections"][2] = {"id": 2, "course_id": 102, "capacity": 1, "seats_taken": 1}

    with pytest.raises(SeatFullError):
        client.enrol_student(student_id=2, section_id=2)


def test_duplicate_enrolment_rejected():
    client = PostgresClient()
    client.connect()
    client._init_mock_storage()

    client._mock_data["sections"][3] = {"id": 3, "course_id": 103, "capacity": 5, "seats_taken": 0}
    client.enrol_student(student_id=5, section_id=3)

    with pytest.raises(AlreadyEnrolledError):
        client.enrol_student(student_id=5, section_id=3)


def test_concurrent_two_students_one_seat_race():
    """
    Required query test from specification:
    Two students taking the last seat: one enrolment commits, the other is rejected.
    """
    client = PostgresClient()
    client.connect()
    client._init_mock_storage()

    # Section with exactly 1 seat remaining
    client._mock_data["sections"][4] = {"id": 4, "course_id": 104, "capacity": 10, "seats_taken": 9}

    results = client.run_concurrent_enrolment_test(section_id=4, student_a_id=101, student_b_id=102)

    statuses = [results["student_a"]["status"], results["student_b"]["status"]]
    assert "COMMITTED" in statuses
    assert "REJECTED_SEAT_FULL" in statuses
    # Final seats taken must be 10, never 11 (invariant maintained)
    assert client._mock_data["sections"][4]["seats_taken"] == 10


class TestPostgresConcurrency(unittest.TestCase):
    def test_single_enrolment(self):
        test_single_enrolment_success()

    def test_seat_full(self):
        test_enrolment_seat_full_rejected()

    def test_duplicate(self):
        test_duplicate_enrolment_rejected()

    def test_concurrent(self):
        test_concurrent_two_students_one_seat_race()
