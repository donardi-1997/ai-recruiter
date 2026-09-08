"""Tests for routers/evaluations.py."""

import json


class TestEvaluationEndpoints:
    def test_get_candidate_job_evaluation(
        self, client, mock_dynamodb_table, mock_current_user
    ):
        def custom_get_item(Key):
            # Evaluation lookup (has both job_id and candidate_id)
            if Key.get("job_id") and Key.get("candidate_id"):
                return {
                    "Item": {
                        "job_id": Key["job_id"],
                        "candidate_id": Key["candidate_id"],
                        "candidate_name": "Alice",
                        "match_score": 85,
                        "recommendation": "STRONG_MATCH",
                        "requirements": json.dumps(
                            [{"requirement": "Python", "status": "MATCH"}]
                        ),
                        "strengths": json.dumps(["Python"]),
                        "gaps": json.dumps([]),
                        "summary": "Good match",
                    }
                }
            # Job lookup
            if Key.get("job_id"):
                return {
                    "Item": {
                        "job_id": Key["job_id"],
                        "owner_id": mock_current_user["sub"],
                        "title": "Dev",
                    }
                }
            # Candidate lookup
            return {
                "Item": {
                    "candidate_id": Key.get("candidate_id"),
                    "owner_id": mock_current_user["sub"],
                    "name": "Alice",
                }
            }

        mock_dynamodb_table.get_item.side_effect = custom_get_item

        response = client.get("/api/jobs/j1/candidates/c1")
        assert response.status_code == 200
        data = response.json()
        assert data["match_score"] == 85

    def test_get_candidate_job_evaluation_not_found(
        self, client, mock_dynamodb_table, mock_current_user
    ):
        def custom_get_item(Key):
            if Key.get("job_id") and Key.get("candidate_id"):
                return {"Item": None}
            return {
                "Item": {
                    "job_id": Key.get("job_id"),
                    "owner_id": mock_current_user["sub"],
                    "title": "Dev",
                }
            }

        mock_dynamodb_table.get_item.side_effect = custom_get_item
        response = client.get("/api/jobs/j1/candidates/c1")
        assert response.status_code == 404

    def test_compare_candidates(
        self, client, mock_dynamodb_table, mock_current_user
    ):
        def custom_get_item(Key):
            return {
                "Item": {
                    "job_id": Key["job_id"],
                    "owner_id": mock_current_user["sub"],
                    "title": "Dev",
                }
            }

        mock_dynamodb_table.get_item.side_effect = custom_get_item
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
        mock_dynamodb_table.query.return_value = {
            "Items": [
                {
                    "job_id": "j1",
                    "candidate_id": "c1",
                    "match_score": 85,
                    "recommendation": "STRONG_MATCH",
                    "strengths": '["Python"]',
                    "gaps": "[]",
                },
                {
                    "job_id": "j1",
                    "candidate_id": "c2",
                    "match_score": 60,
                    "recommendation": "PARTIAL_MATCH",
                    "strengths": '["Java"]',
                    "gaps": '["AWS"]',
                },
            ]
        }

        response = client.get("/api/jobs/j1/compare?candidate_ids=c1,c2")
        assert response.status_code == 200
        data = response.json()
        assert len(data["candidates"]) == 2
        assert data["winner"]["candidate_id"] == "c1"
        assert data["winner"]["match_score"] == 85

    def test_compare_candidates_too_many(
        self, client, mock_dynamodb_table, mock_current_user
    ):
        mock_dynamodb_table.get_item.return_value = {
            "Item": {
                "job_id": "j1",
                "owner_id": mock_current_user["sub"],
                "title": "Dev",
            }
        }
        response = client.get(
            "/api/jobs/j1/compare?candidate_ids=c1,c2,c3,c4,c5,c6"
        )
        assert response.status_code == 400
        assert "M\u00e1ximo 5" in response.json()["detail"]
