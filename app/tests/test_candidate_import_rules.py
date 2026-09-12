"""Unit contracts for deterministic candidate-import rules."""

import hashlib
import importlib

import pytest


def _rules():
    try:
        return importlib.import_module("app.domains.candidate_imports.rules")
    except ModuleNotFoundError as exc:
        pytest.fail(f"candidate import rules module is missing: {exc}")


def test_normalize_email_is_trimmed_and_casefolded():
    rules = _rules()
    assert rules.normalize_email("  ANA@Example.COM \n") == "ana@example.com"


def test_normalize_phone_keeps_leading_plus_and_digits_only():
    rules = _rules()
    assert rules.normalize_phone("+57 (300) 123-4567") == "+573001234567"
    assert rules.normalize_phone("(300) 123-4567") == "3001234567"


def test_document_sha256_is_deterministic():
    rules = _rules()
    payload = b"candidate-cv"
    assert rules.document_sha256(payload) == hashlib.sha256(payload).hexdigest()


def test_strong_identities_can_resolve_to_one_candidate():
    rules = _rules()
    assert rules.resolve_identity_candidates({"EMAIL": "candidate-1", "PHONE": "candidate-1"}) == "candidate-1"
    assert rules.resolve_identity_candidates({}) is None


def test_conflicting_strong_identities_never_merge_candidates():
    rules = _rules()
    with pytest.raises(rules.IdentityConflict, match="IDENTITY_CONFLICT"):
        rules.resolve_identity_candidates({"EMAIL": "candidate-1", "PHONE": "candidate-2"})


def test_queued_batch_enters_processing_when_validation_starts():
    rules = _rules()
    assert rules.transition_batch("QUEUED", "UPLOADING", "VALIDATING") == (
        "PROCESSING",
        "VALIDATING",
    )


def test_processing_batch_can_skip_ingestion_when_nothing_changed():
    rules = _rules()
    assert rules.transition_batch("PROCESSING", "DEDUPLICATING", "EVALUATING") == (
        "PROCESSING",
        "EVALUATING",
    )


def test_terminal_batch_cannot_reactivate():
    rules = _rules()
    with pytest.raises(rules.InvalidTransition):
        rules.transition_batch("COMPLETED", "COMPLETED", "EVALUATING")


def test_stage_cannot_move_backwards():
    rules = _rules()
    with pytest.raises(rules.InvalidTransition):
        rules.transition_batch("PROCESSING", "EVALUATING", "DEDUPLICATING")
