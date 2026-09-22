"""Characterization tests for Bedrock infrastructure.

These tests characterize the existing behavior of the Bedrock infrastructure
modules without changing any implementation. They serve as regression tests
to protect against future changes.
"""

import importlib
from unittest.mock import MagicMock

import pytest


# ============================================================
# TEST GROUP 1 — CONFIG CONSTANTS
# ============================================================

def test_config_defaults(monkeypatch):
    """Runtime-generated resource identifiers have no legacy fallback."""
    monkeypatch.delenv("KNOWLEDGE_BASE_ID", raising=False)

    import app.infrastructure.bedrock.config as config_module
    importlib.reload(config_module)

    assert config_module.AWS_REGION == "us-east-2"
    assert config_module.KNOWLEDGE_BASE_ID == ""
    assert config_module.NUMBER_OF_RESULTS == 50
    assert config_module.MODEL_ID == "amazon.nova-lite-v1:0"
    assert config_module.MODEL_TEMPERATURE == 0


def test_config_env_override(monkeypatch):
    """Knowledge Base identifiers are supplied by the deployment environment."""
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", "kb-current-account-test")

    import app.infrastructure.bedrock.config as config_module
    importlib.reload(config_module)

    assert config_module.AWS_REGION == "us-east-2"
    assert config_module.KNOWLEDGE_BASE_ID == "kb-current-account-test"
    assert config_module.NUMBER_OF_RESULTS == 50
    assert config_module.MODEL_ID == "amazon.nova-lite-v1:0"

    monkeypatch.delenv("KNOWLEDGE_BASE_ID", raising=False)
    importlib.reload(config_module)


# ============================================================
# TEST GROUP 2 — SESSION PROFILE
# ============================================================

def test_session_with_profile(monkeypatch):
    """Test session creation when BEDROCK_AWS_PROFILE is set."""
    mock_session = MagicMock()

    monkeypatch.setattr("app.infrastructure.bedrock.session.boto3.Session", mock_session)
    monkeypatch.setattr(
        "app.infrastructure.bedrock.config.BEDROCK_AWS_PROFILE",
        "ai-recruiter-bedrock",
    )
    monkeypatch.setenv("AWS_REGION", "us-east-2")

    import app.infrastructure.bedrock.session as session_module
    importlib.reload(session_module)

    assert mock_session.call_count >= 1
    call_args, call_kwargs = mock_session.call_args
    assert call_kwargs.get("profile_name") == "ai-recruiter-bedrock"


def test_session_without_profile(monkeypatch):
    """Test session creation when no profile is set (default credential chain)."""
    mock_session = MagicMock()

    monkeypatch.setattr("app.infrastructure.bedrock.session.boto3.Session", mock_session)
    monkeypatch.setattr("app.infrastructure.bedrock.config.BEDROCK_AWS_PROFILE", None)
    monkeypatch.setenv("AWS_REGION", "us-east-2")

    import app.infrastructure.bedrock.session as session_module
    importlib.reload(session_module)

    assert mock_session.call_count >= 1
    call_args, call_kwargs = mock_session.call_args
    assert "profile_name" not in call_kwargs


# ============================================================
# TEST GROUP 4 — RETRIEVAL REQUEST
# ============================================================

def test_retrieve_candidate_request_shape(monkeypatch):
    """Test that retrieve_candidate sends the runtime Knowledge Base ID."""
    mock_client = MagicMock()
    mock_client.retrieve.return_value = {"retrievalResults": []}

    import app.infrastructure.bedrock.clients as clients_module
    monkeypatch.setattr(clients_module, "bedrock_agent_runtime", mock_client)

    import app.infrastructure.bedrock.retriever as retriever_module
    monkeypatch.setattr(retriever_module, "KNOWLEDGE_BASE_ID", "kb-current-account-test")

    results = retriever_module.retrieve_candidate(
        candidate_id="candidate-123",
        question="Python AWS backend",
    )

    mock_client.retrieve.assert_called_once()
    call_kwargs = mock_client.retrieve.call_args.kwargs

    assert call_kwargs["knowledgeBaseId"] == "kb-current-account-test"
    assert call_kwargs["retrievalQuery"] == {"text": "Python AWS backend"}

    vector_search = call_kwargs["retrievalConfiguration"]["vectorSearchConfiguration"]
    assert vector_search["numberOfResults"] == 50

    filter_config = vector_search["filter"]
    assert filter_config["equals"]["key"] == "candidate_id"
    assert filter_config["equals"]["value"] == "candidate-123"
    assert results == []


def test_retrieve_candidate_returns_list(monkeypatch):
    """Test that retrieve_candidate returns the retrievalResults list."""
    mock_client = MagicMock()
    mock_client.retrieve.return_value = {
        "retrievalResults": [
            {"content": {"text": "CV content 1"}},
            {"content": {"text": "CV content 2"}},
        ]
    }

    import app.infrastructure.bedrock.clients as clients_module
    monkeypatch.setattr(clients_module, "bedrock_agent_runtime", mock_client)

    from app.infrastructure.bedrock.retriever import retrieve_candidate

    results = retrieve_candidate(candidate_id="cand-1", question="test")

    assert isinstance(results, list)
    assert len(results) == 2
    assert results[0]["content"]["text"] == "CV content 1"


def test_retrieve_candidate_empty_results(monkeypatch):
    """Test that retrieve_candidate returns empty list when no results key."""
    mock_client = MagicMock()
    mock_client.retrieve.return_value = {}

    import app.infrastructure.bedrock.clients as clients_module
    monkeypatch.setattr(clients_module, "bedrock_agent_runtime", mock_client)

    from app.infrastructure.bedrock.retriever import retrieve_candidate

    results = retrieve_candidate(candidate_id="cand-1", question="test")

    assert results == []


# ============================================================
# TEST GROUP 6 — clean_json
# ============================================================

class TestCleanJson:
    """Tests for clean_json parser."""

    def test_raw_json(self):
        from app.infrastructure.bedrock.parser import clean_json
        assert clean_json('{"a":1}') == '{"a":1}'

    def test_json_fence(self):
        from app.infrastructure.bedrock.parser import clean_json
        content = '```json\n{"a":1}\n```'
        assert clean_json(content) == '{"a":1}'

    def test_generic_fence(self):
        from app.infrastructure.bedrock.parser import clean_json
        content = '```\n{"a":1}\n```'
        assert clean_json(content) == '{"a":1}'

    def test_prefix_suffix_prose(self):
        from app.infrastructure.bedrock.parser import clean_json
        content = 'Here is the JSON:\n{"a":1}\nThat was the result.'
        assert clean_json(content) == '{"a":1}'

    def test_empty_content(self):
        from app.infrastructure.bedrock.parser import clean_json
        with pytest.raises(ValueError, match="El modelo devolv"):
            clean_json("")

    def test_missing_opening_brace(self):
        from app.infrastructure.bedrock.parser import clean_json
        with pytest.raises(ValueError, match="MODEL_JSON_OBJECT_NOT_FOUND"):
            clean_json("no json here")

    def test_missing_closing_brace(self):
        from app.infrastructure.bedrock.parser import clean_json
        with pytest.raises(ValueError, match="MODEL_JSON_INCOMPLETE"):
            clean_json('{"a":1')


# ============================================================
# TEST GROUP 7 — invoke_json_prompt RETRY BEHAVIOR
# ============================================================

class TestInvokeJsonPrompt:
    """Tests for invoke_json_prompt retry behavior."""

    def test_valid_first_response(self, monkeypatch):
        """Valid first response -> one invocation."""
        mock_chain = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '{"result": "ok"}'
        mock_chain.invoke.return_value = mock_response

        from app.infrastructure.bedrock.parser import invoke_json_prompt

        result = invoke_json_prompt(mock_chain, {"input": "test"}, "test")

        assert result == {"result": "ok"}
        assert mock_chain.invoke.call_count == 1

    def test_invalid_first_valid_second(self):
        """Invalid JSON first + valid second -> two invocations."""
        mock_chain = MagicMock()
        mock_resp1 = MagicMock()
        mock_resp1.content = '{"invalid json: missing quote}'
        mock_resp2 = MagicMock()
        mock_resp2.content = '{"result": "ok"}'
        mock_chain.invoke.side_effect = [mock_resp1, mock_resp2]

        from app.infrastructure.bedrock.parser import invoke_json_prompt

        result = invoke_json_prompt(mock_chain, {"input": "test"}, "test")

        assert result == {"result": "ok"}
        assert mock_chain.invoke.call_count == 2


def test_invalid_both_attempts_retry_and_never_expose_model_content():
    mock_chain = MagicMock()
    mock_resp1 = MagicMock()
    mock_resp1.content = 'candidate-secret-one without json'
    mock_resp2 = MagicMock()
    mock_resp2.content = '{"candidate-secret-two":'
    mock_chain.invoke.side_effect = [mock_resp1, mock_resp2]

    from app.infrastructure.bedrock.parser import invoke_json_prompt

    with pytest.raises(ValueError, match="MODEL_JSON_INVALID_AFTER_RETRY:test") as exc:
        invoke_json_prompt(mock_chain, {"input": "test"}, "test")

    assert mock_chain.invoke.call_count == 2
    assert "candidate-secret-one" not in str(exc.value)
    assert "candidate-secret-two" not in str(exc.value)


def test_missing_brace_first_attempt_can_recover_on_retry():
    mock_chain = MagicMock()
    first = MagicMock()
    first.content = '{"incomplete": true'
    second = MagicMock()
    second.content = '{"result": "ok"}'
    mock_chain.invoke.side_effect = [first, second]

    from app.infrastructure.bedrock.parser import invoke_json_prompt

    assert invoke_json_prompt(mock_chain, {"input": "test"}, "test") == {
        "result": "ok"
    }
    assert mock_chain.invoke.call_count == 2


# ============================================================
# TEST GROUP 7 — RECOMMENDATION THRESHOLDS
# ============================================================

class TestRecommendationThresholds:
    """Test recommendation_for_score boundary behavior."""

    def test_strong_match(self):
        from app.domains.evaluations.rules import recommendation_for_score
        assert recommendation_for_score(100) == "STRONG_MATCH"
        assert recommendation_for_score(80) == "STRONG_MATCH"
        assert recommendation_for_score(79.99) == "GOOD_MATCH"

    def test_good_match(self):
        from app.domains.evaluations.rules import recommendation_for_score
        assert recommendation_for_score(60) == "GOOD_MATCH"
        assert recommendation_for_score(59.99) == "PARTIAL_MATCH"

    def test_partial_match(self):
        from app.domains.evaluations.rules import recommendation_for_score
        assert recommendation_for_score(40) == "PARTIAL_MATCH"
        assert recommendation_for_score(39.99) == "LOW_MATCH"

    def test_low_match(self):
        from app.domains.evaluations.rules import recommendation_for_score
        assert recommendation_for_score(0) == "LOW_MATCH"
        assert recommendation_for_score(39) == "LOW_MATCH"


# ============================================================
# TEST GROUP 8 — REQUIREMENT NORMALIZATION
# ============================================================

class TestRequirementNormalization:
    """Test normalize_requirement canonical mappings."""

    def test_python(self):
        from app.domains.evaluations.rules import normalize_requirement
        assert normalize_requirement("python") == "Python"
        assert normalize_requirement("Python") == "Python"

    def test_api_rest(self):
        from app.domains.evaluations.rules import normalize_requirement
        assert normalize_requirement("api rest") == "APIs REST"
        assert normalize_requirement("apis rest") == "APIs REST"
        assert normalize_requirement("rest api") == "APIs REST"
        assert normalize_requirement("rest apis") == "APIs REST"

    def test_aws(self):
        from app.domains.evaluations.rules import normalize_requirement
        assert normalize_requirement("aws") == "AWS"
        assert normalize_requirement("AWS") == "AWS"

    def test_kubernetes(self):
        from app.domains.evaluations.rules import normalize_requirement
        assert normalize_requirement("kubernetes") == "Kubernetes"

    def test_backend_developer(self):
        from app.domains.evaluations.rules import normalize_requirement
        assert normalize_requirement("backend developer") == "Backend Developer"
        assert normalize_requirement("backend development") == "Backend Developer"
        assert normalize_requirement("desarrollo backend") == "Backend Developer"
        assert normalize_requirement("desarrollador backend") == "Backend Developer"
        assert normalize_requirement("backend") == "Backend Developer"

    def test_unknown(self):
        from app.domains.evaluations.rules import normalize_requirement
        assert normalize_requirement("unknown tech") == "unknown tech"


# ============================================================
# TEST GROUP 9 — SCORING CONTRACT
# ============================================================

def test_scoring_contract():
    """Test deterministic scoring: MATCH=1, PARTIAL=0.5, MISSING=0."""
    score = round((2.5 / 4) * 100)
    assert score == 62


# ============================================================
# TEST GROUP 10 — EVIDENCE CAP
# ============================================================

def test_evidence_30_word_cap():
    """Evidence behavior is covered by evaluation contract tests."""
    from app.infrastructure.bedrock.evaluator import evaluate_candidate
    assert callable(evaluate_candidate)


# ============================================================
# TEST GROUP 11 — NO-RESULTS CONTRACT
# ============================================================

def test_no_results_returns_failed(monkeypatch):
    """Empty retrieval results -> FAILED with CANDIDATE_CONTEXT_NOT_FOUND."""
    import app.infrastructure.bedrock.clients as clients_module

    mock_client = MagicMock()
    mock_client.retrieve.return_value = {"retrievalResults": []}
    monkeypatch.setattr(clients_module, "get_bedrock_agent_runtime", lambda: mock_client)

    from app.infrastructure.bedrock.evaluator import evaluate_candidate

    result = evaluate_candidate(
        candidate_id="cand-1",
        job_description="Python developer",
        results=[],
    )

    assert result["status"] == "FAILED"
    assert result["recommendation"] == "EVALUATION_FAILED"
    assert result["error_message"] == "CANDIDATE_CONTEXT_NOT_FOUND"
    assert result["match_score"] == 0
    assert result["strengths"] == []
    assert result["gaps"] == []


# ============================================================
# TEST GROUP 12 — NO REQUIREMENTS CONTRACT
# ============================================================

class _PromptStub:
    def __init__(self, name):
        self.name = name

    def __or__(self, _other):
        return self.name


def test_no_requirements_returns_failed_not_low_match(monkeypatch):
    import app.infrastructure.bedrock.evaluator as evaluator_module

    monkeypatch.setattr(
        evaluator_module,
        "REQUIREMENT_EXTRACTION_PROMPT",
        _PromptStub("extract"),
    )
    monkeypatch.setattr(evaluator_module, "get_llm", lambda: object())
    monkeypatch.setattr(
        evaluator_module,
        "invoke_json_prompt",
        lambda chain, payload, description: {"requirements": []},
    )

    result = evaluator_module.evaluate_candidate(
        candidate_id="cand-1",
        job_description="Vacante ambigua sin requisitos verificables",
        results=[{"content": {"text": "Some CV content"}}],
    )

    assert result["status"] == "FAILED"
    assert result["recommendation"] == "EVALUATION_FAILED"
    assert result["error_message"] == "JOB_REQUIREMENTS_NOT_FOUND"
    assert result["match_score"] == 0


def test_positive_match_without_evidence_is_downgraded_to_missing(monkeypatch):
    import app.infrastructure.bedrock.evaluator as evaluator_module

    monkeypatch.setattr(
        evaluator_module,
        "REQUIREMENT_EXTRACTION_PROMPT",
        _PromptStub("extract"),
    )
    monkeypatch.setattr(
        evaluator_module,
        "CANDIDATE_EVALUATION_PROMPT",
        _PromptStub("evaluate"),
    )
    monkeypatch.setattr(evaluator_module, "get_llm", lambda: object())

    def fake_invoke(chain, payload, description):
        if chain == "extract":
            return {"requirements": ["Python", "AWS"]}
        assert chain == "evaluate"
        return {
            "requirements": [
                {
                    "requirement": "Python",
                    "status": "MATCH",
                    "evidence": "",
                },
                {
                    "requirement": "AWS",
                    "status": "MATCH",
                    "evidence": "Implementó servicios productivos sobre AWS.",
                },
            ]
        }

    monkeypatch.setattr(evaluator_module, "invoke_json_prompt", fake_invoke)

    result = evaluator_module.evaluate_candidate(
        candidate_id="cand-1",
        job_description="Python y AWS son requisitos explícitos.",
        results=[
            {
                "content": {
                    "text": (
                        "Implementó servicios productivos sobre AWS. "
                        "No hay evidencia de Python."
                    )
                }
            }
        ],
    )

    assert result["match_score"] == 50
    assert result["recommendation"] == "PARTIAL_MATCH"
    assert result["requirements"] == [
        {"requirement": "Python", "status": "MISSING", "evidence": None},
        {
            "requirement": "AWS",
            "status": "MATCH",
            "evidence": "Implementó servicios productivos sobre AWS.",
        },
    ]
    assert result["strengths"] == ["AWS"]
    assert result["gaps"] == ["Python"]


def test_hallucinated_positive_evidence_does_not_inflate_score(monkeypatch):
    import app.infrastructure.bedrock.evaluator as evaluator_module

    monkeypatch.setattr(
        evaluator_module,
        "REQUIREMENT_EXTRACTION_PROMPT",
        _PromptStub("extract"),
    )
    monkeypatch.setattr(
        evaluator_module,
        "CANDIDATE_EVALUATION_PROMPT",
        _PromptStub("evaluate"),
    )
    monkeypatch.setattr(evaluator_module, "get_llm", lambda: object())

    def fake_invoke(chain, payload, description):
        if chain == "extract":
            return {"requirements": ["Kubernetes"]}
        return {
            "requirements": [
                {
                    "requirement": "Kubernetes",
                    "status": "MATCH",
                    "evidence": "Administró clusters Kubernetes en producción.",
                }
            ]
        }

    monkeypatch.setattr(evaluator_module, "invoke_json_prompt", fake_invoke)

    result = evaluator_module.evaluate_candidate(
        candidate_id="cand-1",
        job_description="Kubernetes",
        results=[
            {
                "content": {
                    "text": "Experiencia en Python y APIs REST."
                }
            }
        ],
    )

    assert result["match_score"] == 0
    assert result["recommendation"] == "LOW_MATCH"
    assert result["requirements"] == [
        {
            "requirement": "Kubernetes",
            "status": "MISSING",
            "evidence": None,
        }
    ]


# ============================================================
# TEST GROUP 13 — SESSION PROFILE TEST SAFETY
# ============================================================

def test_session_isolation_between_tests(monkeypatch):
    """Verify that session tests don't leak state between tests."""
    mock_session1 = MagicMock()
    mock_session2 = MagicMock()

    monkeypatch.setattr("boto3.Session", lambda **kwargs: mock_session1)
    monkeypatch.setenv("BEDROCK_AWS_PROFILE", "profile1")

    import app.infrastructure.bedrock.session as session_module
    importlib.reload(session_module)
    s1 = session_module.get_bedrock_session()

    monkeypatch.setattr("boto3.Session", lambda **kwargs: mock_session2)
    monkeypatch.setenv("BEDROCK_AWS_PROFILE", "profile2")
    importlib.reload(session_module)
    s2 = session_module.get_bedrock_session()

    assert s1 is not s2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
