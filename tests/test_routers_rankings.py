"""Tests for routers/rankings.py."""

import json
from unittest.mock import patch


class TestRankingEndpoints:
    def test_get_job_ranking_empty(
        self, client, mock_dynamodb_table, mock_current_user
    ):
        mock_dynamodb_table.get_item.return_value = {
            "Item": {
                "job_id": "j1",
                "owner_id": mock_current_user["sub"],
                "title": "Dev",
            }
        }
        mock_dynamodb_table.query.return_value = {"Items": []}
        mock_dynamodb_table.scan.return_value = {"Items": []}

        response = client.get("/api/jobs/j1/ranking")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["candidates"] == []

    def test_get_job_ranking_with_candidates(
        self, client, mock_dynamodb_table, mock_current_user
    ):
        mock_dynamodb_table.get_item.return_value = {
            "Item": {
                "job_id": "j1",
                "owner_id": mock_current_user["sub"],
                "title": "Dev",
            }
        }

        # Use a side_effect that returns different data based on call order
        call_count = [0]

        def custom_query(**kwargs):
            call_count[0] += 1
            # First call: job_candidates query (get_job_candidate_ids)
            if call_count[0] == 1:
                return {
                    "Items": [
                        {"job_id": "j1", "candidate_id": "c1"},
                        {"job_id": "j1", "candidate_id": "c2"},
                    ]
                }
            # Second call: evaluations query
            return {
                "Items": [
                    {
                        "job_id": "j1",
                        "candidate_id": "c1",
                        "match_score": 85,
                        "recommendation": "STRONG_MATCH",
                        "status": "COMPLETED",
                        "strengths": '["Python"]',
                        "gaps": "[]",
                    },
                    {
                        "job_id": "j1",
                        "candidate_id": "c2",
                        "match_score": 60,
                        "recommendation": "PARTIAL_MATCH",
                        "status": "COMPLETED",
                        "strengths": '["Java"]',
                        "gaps": '["AWS"]',
                    },
                ]
            }

        mock_dynamodb_table.query.side_effect = custom_query
        mock_dynamodb_table.scan.return_value = {
            "Items": [
                {
                    "candidate_id": "c1",
                    "owner_id": mock_current_user["sub"],
                    "name": "Alice",
                },
                {
                    "candidate_id": "c2",
                    "owner_id": mock_current_user["sub"],
                    "name": "Bob",
                },
            ]
        }

        response = client.get("/api/jobs/j1/ranking")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["candidates"][0]["match_score"] == 85
        assert data["candidates"][0]["rank"] == 1

    def test_get_job_ranking_with_filters(
        self, client, mock_dynamodb_table, mock_current_user
    ):
        mock_dynamodb_table.get_item.return_value = {
            "Item": {
                "job_id": "j1",
                "owner_id": mock_current_user["sub"],
                "title": "Dev",
            }
        }

        call_count = [0]

        def custom_query(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return {
                    "Items": [{"job_id": "j1", "candidate_id": "c1"}]
                }
            return {
                "Items": [
                    {
                        "job_id": "j1",
                        "candidate_id": "c1",
                        "match_score": 85,
                        "recommendation": "STRONG_MATCH",
                        "status": "COMPLETED",
                        "strengths": "[]",
                        "gaps": "[]",
                    },
                ]
            }

        mock_dynamodb_table.query.side_effect = custom_query
        mock_dynamodb_table.scan.return_value = {
            "Items": [
                {"candidate_id": "c1", "owner_id": mock_current_user["sub"], "name": "Alice"},
            ]
        }

        response = client.get("/api/jobs/j1/ranking?min_score=80")
        assert response.status_code == 200

    def test_get_job_ranking_invalid_params(
        self, client, mock_dynamodb_table, mock_current_user
    ):
        mock_dynamodb_table.get_item.return_value = {
            "Item": {
                "job_id": "j1",
                "owner_id": mock_current_user["sub"],
                "title": "Dev",
            }
        }

        response = client.get("/api/jobs/j1/ranking?min_score=101")
        assert response.status_code == 400

    def test_get_job_ranking_not_found(self, client, mock_dynamodb_table):
        mock_dynamodb_table.get_item.return_value = {"Item": None}
        response = client.get("/api/jobs/nonexistent/ranking")
        assert response.status_code == 404

    def test_recalculate_job_ranking(
        self, client, mock_dynamodb_table, mock_current_user
    ):
        mock_dynamodb_table.get_item.return_value = {
            "Item": {
                "job_id": "j1",
                "owner_id": mock_current_user["sub"],
                "title": "Dev",
            }
        }

        call_count = [0]

        def custom_query(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"Items": [{"job_id": "j1", "candidate_id": "c1"}]}
            return {"Items": []}

        mock_dynamodb_table.query.side_effect = custom_query
        mock_dynamodb_table.scan.return_value = {
            "Items": [
                {"candidate_id": "c1", "owner_id": mock_current_user["sub"], "name": "Alice"}
            ]
        }

        with patch("core.llm.evaluate_and_save") as mock_eval:
            mock_eval.return_value = {
                "candidate_id": "c1",
                "match_score": 85,
                "recommendation": "STRONG_MATCH",
                "requirements": [],
                "strengths": [],
                "gaps": [],
                "summary": "Good",
                "sources": [],
            }
            response = client.post("/api/jobs/j1/ranking/recalculate")

        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "j1"
        assert data["evaluated"] == 1

    def test_recalculate_invalid_mode(
        self, client, mock_dynamodb_table, mock_current_user
    ):
        mock_dynamodb_table.get_item.return_value = {
            "Item": {
                "job_id": "j1",
                "owner_id": mock_current_user["sub"],
                "title": "Dev",
            }
        }
        response = client.post("/api/jobs/j1/ranking/recalculate?mode=invalid")
        assert response.status_code == 400
