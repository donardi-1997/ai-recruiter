"""Tests for routers/jobs.py."""

from unittest.mock import patch


class TestJobEndpoints:
    def test_list_jobs_empty(self, client, mock_dynamodb_table):
        mock_dynamodb_table.scan.return_value = {"Items": []}
        response = client.get("/api/jobs")
        assert response.status_code == 200
        data = response.json()
        assert data["jobs"] == []

    def test_list_jobs_filtered_by_owner(
        self, client, mock_dynamodb_table, mock_current_user
    ):
        mock_dynamodb_table.scan.return_value = {
            "Items": [
                {"job_id": "j1", "owner_id": mock_current_user["sub"], "title": "Dev"},
                {"job_id": "j2", "owner_id": "other", "title": "Other Job"},
            ]
        }
        mock_dynamodb_table.query.return_value = {"Items": []}
        response = client.get("/api/jobs")
        assert response.status_code == 200
        data = response.json()
        assert len(data["jobs"]) == 1

    def test_create_job(self, client, mock_dynamodb_table):
        response = client.post(
            "/api/jobs",
            json={"title": "Backend Dev", "description": "Python developer needed"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Backend Dev"
        assert "job_id" in data

    def test_get_job_found(self, client, mock_dynamodb_table, mock_current_user):
        mock_dynamodb_table.get_item.return_value = {
            "Item": {
                "job_id": "j1",
                "owner_id": mock_current_user["sub"],
                "title": "Dev",
                "description": "Python dev",
            }
        }
        response = client.get("/api/jobs/j1")
        assert response.status_code == 200
        assert response.json()["title"] == "Dev"

    def test_get_job_not_found(self, client, mock_dynamodb_table):
        mock_dynamodb_table.get_item.return_value = {"Item": None}
        response = client.get("/api/jobs/nonexistent")
        assert response.status_code == 404

    def test_get_job_forbidden(self, client, mock_dynamodb_table):
        mock_dynamodb_table.get_item.return_value = {
            "Item": {
                "job_id": "j1",
                "owner_id": "other-user",
                "title": "Dev",
            }
        }
        response = client.get("/api/jobs/j1")
        assert response.status_code == 403

    def test_delete_job(self, client, mock_dynamodb_table, mock_current_user):
        mock_dynamodb_table.get_item.return_value = {
            "Item": {
                "job_id": "j1",
                "owner_id": mock_current_user["sub"],
                "title": "Dev",
            }
        }
        mock_dynamodb_table.scan.return_value = {"Items": []}
        response = client.delete("/api/jobs/j1")
        assert response.status_code == 200
        assert "eliminada" in response.json()["message"]

    def test_delete_job_not_found(self, client, mock_dynamodb_table):
        mock_dynamodb_table.get_item.return_value = {"Item": None}
        response = client.delete("/api/jobs/nonexistent")
        assert response.status_code == 404

    def test_assign_candidates(self, client, mock_dynamodb_table, mock_current_user):
        def custom_get_item(Key):
            if Key.get("job_id") == "j1" and not Key.get("candidate_id"):
                return {"Item": {
                    "job_id": "j1",
                    "owner_id": mock_current_user["sub"],
                    "title": "Dev",
                }}
            return {"Item": {
                "candidate_id": Key.get("candidate_id"),
                "owner_id": mock_current_user["sub"],
                "name": "Alice",
            }}

        mock_dynamodb_table.get_item.side_effect = custom_get_item

        response = client.post(
            "/api/jobs/j1/candidates",
            json={"candidate_ids": ["c1", "c2"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["assigned"] == 2

    def test_assign_candidates_job_not_found(
        self, client, mock_dynamodb_table
    ):
        mock_dynamodb_table.get_item.return_value = {"Item": None}
        response = client.post(
            "/api/jobs/nonexistent/candidates",
            json={"candidate_ids": ["c1"]},
        )
        assert response.status_code == 404

    def test_unassign_candidate(self, client, mock_dynamodb_table, mock_current_user):
        def custom_get_item(Key):
            if Key.get("job_id") == "j1" and not Key.get("candidate_id"):
                return {"Item": {
                    "job_id": "j1",
                    "owner_id": mock_current_user["sub"],
                }}
            return {"Item": {
                "candidate_id": Key.get("candidate_id"),
                "owner_id": mock_current_user["sub"],
            }}

        mock_dynamodb_table.get_item.side_effect = custom_get_item

        response = client.delete("/api/jobs/j1/candidates/c1")
        assert response.status_code == 200
        assert response.json()["unassigned"] is True

    def test_get_job_evaluations(self, client, mock_dynamodb_table, mock_current_user):
        mock_dynamodb_table.get_item.return_value = {
            "Item": {
                "job_id": "j1",
                "owner_id": mock_current_user["sub"],
                "title": "Dev",
            }
        }
        mock_dynamodb_table.query.return_value = {
            "Items": [
                {
                    "job_id": "j1",
                    "candidate_id": "c1",
                    "match_score": 85,
                    "recommendation": "STRONG_MATCH",
                    "requirements": "[]",
                    "strengths": '["Python"]',
                    "gaps": "[]",
                }
            ]
        }
        response = client.get("/api/jobs/j1/evaluations")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["evaluations"][0]["match_score"] == 85

    def test_get_job_summary(self, client, mock_dynamodb_table, mock_current_user):
        mock_dynamodb_table.get_item.return_value = {
            "Item": {
                "job_id": "j1",
                "owner_id": mock_current_user["sub"],
                "title": "Dev",
            }
        }
        mock_dynamodb_table.query.return_value = {
            "Items": [
                {
                    "job_id": "j1",
                    "candidate_id": "c1",
                    "match_score": 85,
                    "recommendation": "STRONG_MATCH",
                    "status": "COMPLETED",
                }
            ]
        }
        mock_dynamodb_table.scan.return_value = {
            "Items": [
                {"candidate_id": "c1", "owner_id": mock_current_user["sub"]},
            ]
        }
        response = client.get("/api/jobs/j1/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "j1"
        assert data["evaluated_candidates"] == 1
