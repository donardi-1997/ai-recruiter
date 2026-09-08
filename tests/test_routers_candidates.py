"""Tests for routers/candidates.py."""

from unittest.mock import patch, MagicMock


class TestCandidateEndpoints:
    def test_list_candidates_empty(self, client, mock_dynamodb_table):
        mock_dynamodb_table.scan.return_value = {"Items": []}
        response = client.get("/api/candidates")
        assert response.status_code == 200
        data = response.json()
        assert data["candidates"] == []

    def test_list_candidates_filtered_by_owner(
        self, client, mock_dynamodb_table, mock_current_user
    ):
        mock_dynamodb_table.scan.return_value = {
            "Items": [
                {"candidate_id": "c1", "owner_id": mock_current_user["sub"], "name": "Alice"},
                {"candidate_id": "c2", "owner_id": "other-user", "name": "Bob"},
            ]
        }
        response = client.get("/api/candidates")
        assert response.status_code == 200
        data = response.json()
        assert len(data["candidates"]) == 1
        assert data["candidates"][0]["name"] == "Alice"

    def test_get_candidate_found(self, client, mock_dynamodb_table, mock_current_user):
        mock_dynamodb_table.get_item.return_value = {
            "Item": {
                "candidate_id": "c1",
                "owner_id": mock_current_user["sub"],
                "name": "Alice",
                "filename": "cv-c1.pdf",
                "s3_location": "s3://bucket/documents/cv-c1.pdf",
                "ingestion_status": "COMPLETE",
                "indexed": True,
            }
        }
        response = client.get("/api/candidates/c1")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Alice"
        assert data["indexed"] is True

    def test_get_candidate_not_found(self, client, mock_dynamodb_table):
        mock_dynamodb_table.get_item.return_value = {"Item": None}
        response = client.get("/api/candidates/nonexistent")
        assert response.status_code == 404

    def test_get_candidate_forbidden(self, client, mock_dynamodb_table):
        mock_dynamodb_table.get_item.return_value = {
            "Item": {
                "candidate_id": "c1",
                "owner_id": "other-user",
                "name": "Bob",
            }
        }
        response = client.get("/api/candidates/c1")
        assert response.status_code == 403

    def test_delete_candidate(self, client, mock_dynamodb_table, mock_current_user):
        mock_dynamodb_table.get_item.return_value = {
            "Item": {
                "candidate_id": "c1",
                "owner_id": mock_current_user["sub"],
                "name": "Alice",
                "s3_location": "s3://bucket/documents/cv-c1.pdf",
            }
        }
        mock_dynamodb_table.query.return_value = {"Items": []}
        response = client.delete("/api/candidates/c1")
        assert response.status_code == 200
        assert "eliminado" in response.json()["message"]

    def test_delete_candidate_not_found(self, client, mock_dynamodb_table):
        mock_dynamodb_table.get_item.return_value = {"Item": None}
        response = client.delete("/api/candidates/nonexistent")
        assert response.status_code == 404

    def test_create_candidate_missing_name(self, client):
        response = client.post("/api/candidates", data={"name": "  "})
        assert response.status_code == 422 or response.status_code == 400

    def test_create_candidate_non_pdf(self, client):
        response = client.post(
            "/api/candidates",
            data={"name": "Alice"},
            files={"file": ("cv.txt", b"not a pdf", "text/plain")},
        )
        assert response.status_code == 400
        assert "PDF" in response.json()["detail"]
