"""Pure unit tests: no database needed."""
from app.filters import Filters, where_sql


def test_empty_filters_give_no_clauses():
    assert where_sql(Filters()) == ([], {})


def test_values_are_bound_not_interpolated():
    clauses, params = where_sql(Filters(action=["ESCALATE"], min_confidence=0.5, coverage_class="sparse"))
    assert all("ESCALATE" not in c and "sparse" not in c for c in clauses)
    assert params["action"] == ["ESCALATE"] and params["min_conf"] == 0.5 and params["cov"] == "sparse"


def test_review_only_adds_clause():
    clauses, _ = where_sql(Filters(review_only=True))
    assert clauses == ["v.solar_review IS TRUE"]
