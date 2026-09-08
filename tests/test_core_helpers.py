"""Tests for core/helpers.py - JSON helpers and DynamoDB helpers."""

import json
import pytest


# ============================================================
# clean_json
# ============================================================


class TestCleanJson:
    def test_valid_json_object(self):
        from core.helpers import clean_json

        result = clean_json('{"key": "value"}')
        assert result == '{"key": "value"}'

    def test_json_with_markdown_fence(self):
        from core.helpers import clean_json

        result = clean_json('```json\n{"key": "value"}\n```')
        assert result == '{"key": "value"}'

    def test_json_with_generic_fence(self):
        from core.helpers import clean_json

        result = clean_json('```\n{"key": "value"}\n```')
        assert result == '{"key": "value"}'

    def test_json_with_surrounding_text(self):
        from core.helpers import clean_json

        result = clean_json('Here is the result: {"key": "value"} done.')
        assert result == '{"key": "value"}'

    def test_empty_content_raises(self):
        from core.helpers import clean_json

        with pytest.raises(ValueError, match="vacía"):
            clean_json("")

    def test_none_content_raises(self):
        from core.helpers import clean_json

        with pytest.raises(ValueError, match="vacía"):
            clean_json(None)

    def test_no_json_object_raises(self):
        from core.helpers import clean_json

        with pytest.raises(ValueError, match="No se encontró"):
            clean_json("no json here")

    def test_incomplete_json_raises(self):
        from core.helpers import clean_json

        with pytest.raises(ValueError, match="incompleto"):
            clean_json('{"key": "value"')

    def test_nested_json(self):
        from core.helpers import clean_json

        data = '{"outer": {"inner": [1, 2, 3]}}'
        result = clean_json(data)
        assert json.loads(result) == {"outer": {"inner": [1, 2, 3]}}


# ============================================================
# invoke_json_prompt
# ============================================================


class TestInvokeJsonPrompt:
    def test_valid_json_response(self):
        from core.helpers import invoke_json_prompt

        mock_chain = type("Chain", (), {})()
        mock_response = type("Response", (), {"content": '{"result": "ok"}'})()
        mock_chain.invoke = lambda payload: mock_response

        result = invoke_json_prompt(mock_chain, {"input": "test"}, "test")
        assert result == {"result": "ok"}

    def test_retry_on_invalid_json(self):
        from core.helpers import invoke_json_prompt

        call_count = [0]

        class MockChain:
            def invoke(self, payload):
                call_count[0] += 1
                if call_count[0] == 1:
                    return type("R", (), {"content": '{"invalid": invalid}'})()
                return type("R", (), {"content": '{"result": "ok"}'})()

        result = invoke_json_prompt(MockChain(), {"input": "test"}, "test")
        assert result == {"result": "ok"}
        assert call_count[0] == 2


# ============================================================
# parse_json_field
# ============================================================


class TestParseJsonField:
    def test_parse_valid_json_string(self):
        from core.helpers import parse_json_field

        result = parse_json_field('["a", "b", "c"]')
        assert result == ["a", "b", "c"]

    def test_parse_invalid_json_string(self):
        from core.helpers import parse_json_field

        result = parse_json_field("not json")
        assert result == "not json"

    def test_parse_non_string(self):
        from core.helpers import parse_json_field

        result = parse_json_field([1, 2, 3])
        assert result == [1, 2, 3]

    def test_parse_none(self):
        from core.helpers import parse_json_field

        result = parse_json_field(None)
        assert result is None


# ============================================================
# build_sources
# ============================================================


class TestBuildSources:
    def test_build_sources_from_results(self):
        from core.helpers import build_sources

        results = [
            {
                "location": {"s3Location": {"uri": "s3://bucket/doc.pdf"}},
                "metadata": {"x-amz-bedrock-kb-document-page-number": "1"},
                "score": 0.95,
            },
            {
                "location": {"s3Location": {"uri": "s3://bucket/doc.pdf"}},
                "metadata": {"x-amz-bedrock-kb-document-page-number": "2"},
                "score": 0.85,
            },
        ]
        sources = build_sources(results)
        assert len(sources) == 2
        assert sources[0].file == "s3://bucket/doc.pdf"
        assert sources[0].page == 1
        assert sources[0].score == 0.95

    def test_build_sources_empty(self):
        from core.helpers import build_sources

        sources = build_sources([])
        assert sources == []

    def test_build_sources_dedup_by_page(self):
        from core.helpers import build_sources

        results = [
            {
                "location": {"s3Location": {"uri": "s3://bucket/doc.pdf"}},
                "metadata": {"x-amz-bedrock-kb-document-page-number": "1"},
                "score": 0.80,
            },
            {
                "location": {"s3Location": {"uri": "s3://bucket/doc.pdf"}},
                "metadata": {"x-amz-bedrock-kb-document-page-number": "1"},
                "score": 0.95,
            },
        ]
        sources = build_sources(results)
        assert len(sources) == 1
        assert sources[0].score == 0.95
