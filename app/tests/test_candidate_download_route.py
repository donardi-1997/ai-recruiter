from fastapi import HTTPException

from app.domains.candidates import router


def test_candidate_download_returns_canonical_presigned_url(monkeypatch):
    seen = []
    monkeypatch.setattr(
        router,
        "_require_candidate",
        lambda db, candidate_id, owner_sub: seen.append(
            (db, candidate_id, owner_sub)
        ) or object(),
    )
    monkeypatch.setattr(
        router.import_storage,
        "create_canonical_candidate_download",
        lambda candidate_id, expires_in=300: {
            "url": "https://download.invalid/cv",
            "expires_in": expires_in,
            "key": f"documents/cv-{candidate_id}.pdf",
        },
    )

    db = object()
    result = router.download_candidate_cv(
        "candidate-1",
        db=db,
        _user={"sub": "owner-1"},
    )

    assert seen == [(db, "candidate-1", "owner-1")]
    assert result == {
        "download_url": "https://download.invalid/cv",
        "expires_in": 300,
    }


def test_candidate_download_404_when_canonical_cv_is_missing(monkeypatch):
    monkeypatch.setattr(
        router,
        "_require_candidate",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        router.import_storage,
        "create_canonical_candidate_download",
        lambda *_args, **_kwargs: None,
    )

    try:
        router.download_candidate_cv(
            "candidate-1",
            db=object(),
            _user={"sub": "owner-1"},
        )
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "CV no disponible."
    else:
        raise AssertionError("expected HTTPException")
