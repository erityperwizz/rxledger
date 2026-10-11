"""Schema validation for the GenAI classifier (no model needed).

Author: Erica Mathias
"""

from analysis.genai_drug_classes import CLASS_NAMES, SCHEMA, validate, wilson


def test_valid_answer_passes():
    answer = '{"therapeutic_class": "Diabetes", "confidence": "high"}'
    assert validate(answer) == ("Diabetes", "high")


def test_answers_outside_the_schema_are_rejected():
    assert validate('{"therapeutic_class": "Antidiabetic", "confidence": "high"}') is None
    assert validate('{"therapeutic_class": "Diabetes", "confidence": "sure"}') is None
    assert validate('{"therapeutic_class": "Diabetes"}') is None
    assert validate("Diabetes") is None
    assert validate("[]") is None


def test_schema_enum_matches_class_list():
    assert SCHEMA["properties"]["therapeutic_class"]["enum"] == CLASS_NAMES
    assert len(CLASS_NAMES) == len(set(CLASS_NAMES))


def test_wilson_interval_brackets_the_estimate():
    lo, hi = wilson(85, 100)
    assert lo < 0.85 < hi and 0.75 < lo and hi < 0.92
