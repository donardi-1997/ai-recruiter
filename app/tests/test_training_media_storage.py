"""Unit contracts for private training video storage."""

import os

import pytest

from app.infrastructure.storage import training_media


class FakeS3:
    def __init__(self):
        self.presigned_posts = []
        self.head_response = {
            "ContentLength": 123,
            "ContentType": "video/mp4",
        }

    def generate_presigned_post(self, **kwargs):
        self.presigned_posts.append(kwargs)
        return {
            "url": "https://training.example/upload",
            "fields": {"key": kwargs["Key"]},
        }

    def head_object(self, **kwargs):
        return dict(self.head_response)

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        return (
            f"https://training.example/{Params['Key']}"
            f"?expires={ExpiresIn}"
        )

    def delete_object(self, **kwargs):
        return {}


@pytest.fixture()
def fake_s3(monkeypatch):
    client = FakeS3()
    monkeypatch.setenv("TRAINING_CONTENT_BUCKET", "training-bucket")
    monkeypatch.setattr(training_media, "_s3_client", lambda: client)
    return client


def test_video_upload_is_exact_size_content_type_and_lesson_scoped(fake_s3):
    payload = training_media.create_video_upload(
        lesson_id="lesson-1",
        filename="intro.mp4",
        content_type="video/mp4",
        size_bytes=123,
    )

    assert payload["key"].startswith("training/lessons/lesson-1/")
    call = fake_s3.presigned_posts[0]
    assert call["Bucket"] == "training-bucket"
    assert {"Content-Type": "video/mp4"} in call["Conditions"]
    assert ["content-length-range", 123, 123] in call["Conditions"]


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("video.exe", "video/mp4"),
        ("video.mp4", "application/octet-stream"),
    ],
)
def test_video_upload_rejects_invalid_manifest(fake_s3, filename, content_type):
    with pytest.raises(ValueError):
        training_media.create_video_upload(
            lesson_id="lesson-1",
            filename=filename,
            content_type=content_type,
            size_bytes=123,
        )


def test_finalize_verification_rejects_cross_lesson_key(fake_s3):
    with pytest.raises(ValueError):
        training_media.verify_video_object(
            lesson_id="lesson-1",
            key="training/lessons/lesson-2/video.mp4",
            expected_content_type="video/mp4",
            expected_size_bytes=123,
        )


def test_private_playback_url_is_short_lived(fake_s3):
    url = training_media.create_video_playback_url(
        "training/lessons/lesson-1/video.mp4",
        expires_in=3600,
    )

    assert url.endswith("?expires=3600")
    assert "training/lessons/lesson-1/" in url
