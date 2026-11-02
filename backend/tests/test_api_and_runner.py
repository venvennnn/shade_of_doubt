import uuid

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from app.auth import Principal
from app.config import get_settings
from app.db import Base, get_db, get_engine, reset_engine, session_factory
from app.imaging import FaceBox
from app.main import app, get_principal
from app.models import Asset, Experiment, Job, ProviderTask, Variant
from app.runner import advance_experiment
from app.storage import LocalStorage
from app.youcam import ParsedScore, ParsedTask, ProviderError


class FakeYouCam:
    def __init__(self, fail_baseline=False, ambiguous_on=None):
        self.created = []
        self.fail_baseline = fail_baseline
        self.ambiguous_on = ambiguous_on
        self.downloads = 0

    def register_and_upload(self, filename, content_type, data):
        return "file-" + filename

    def create_task(self, file_id, concerns):
        if self.fail_baseline and not self.created:
            raise ProviderError("error_no_face", "No face detected on source image", "", http_status=400)
        if self.ambiguous_on is not None and len(self.created) == self.ambiguous_on:
            raise ProviderError("task_create_transport", "dropped", "", ambiguous=True)
        task_id = f"task-{len(self.created) + 1}"
        self.created.append(file_id)
        return task_id

    def get_task(self, task_id):
        index = int(task_id.split("-")[1])
        scores = []
        for concern in ["texture", "pore", "redness", "oiliness", "moisture", "acne", "age_spot"]:
            scores.append(
                ParsedScore(
                    concern=concern,
                    region="",
                    raw_score=50 + index + (0.5 if concern == "redness" else 0),
                    ui_score=70 + index,
                    general_score=None,
                    mask_urls=["https://provider.example/overlay.png"] if concern == "texture" else [],
                    raw_available=True,
                )
            )
        return ParsedTask(task_status="success", error_code=None, error_message=None, scores=scores)

    def download(self, url):
        self.downloads += 1
        assert "http" in url
        return b"\x89PNG\r\n\x1a\noverlay"


def _png() -> bytes:
    rng = np.random.default_rng(1)
    array = rng.integers(30, 200, size=(900, 700, 3), dtype=np.uint8)
    image = Image.fromarray(array, mode="RGB")
    import io

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _client(user_id="user-a"):
    reset_engine()
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    def _db():
        session = session_factory()()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_principal] = lambda: Principal(user_id=user_id)
    return TestClient(app)


def test_capture_plan_and_tenant_isolation(monkeypatch):
    monkeypatch.setattr("app.imaging.detect_faces", lambda image: [FaceBox(120, 100, 360, 420)])
    client = _client("user-a")
    denied = client.post("/v1/assets", files={"file": ("selfie.png", _png(), "image/png")})
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "consent_required"
    consent = client.post("/v1/consents", json={"external_processing": True, "retention_acknowledged": True})
    assert consent.status_code == 200
    uploaded = client.post("/v1/assets", files={"file": ("selfie.png", _png(), "image/png")})
    assert uploaded.status_code == 200
    assert uploaded.json()["validation"]["ok"] is True
    asset_id = uploaded.json()["id"]
    plan = client.post("/v1/experiments/plan", json={"concerns": ["texture", "redness"], "product_ids": []})
    assert plan.status_code == 200
    assert plan.json()["task_count"] == 7
    assert plan.json()["estimated_units"] == 84
    created = client.post("/v1/experiments", json={"asset_id": asset_id, "concerns": ["texture", "redness"]}, headers={"Idempotency-Key": "same"})
    assert created.status_code == 202
    again = client.post("/v1/experiments", json={"asset_id": asset_id, "concerns": ["texture", "redness"]}, headers={"Idempotency-Key": "same"})
    assert again.json()["experiment_id"] == created.json()["experiment_id"]
    assert again.json()["created"] is False
    conflict = client.post("/v1/experiments", json={"asset_id": asset_id, "concerns": ["pore"]}, headers={"Idempotency-Key": "same"})
    assert conflict.status_code == 409
    app.dependency_overrides[get_principal] = lambda: Principal(user_id="user-b")
    missing = client.get(f"/v1/experiments/{created.json()['experiment_id']}")
    assert missing.status_code == 404
    hidden = client.get(f"/v1/assets/{asset_id}/content")
    assert hidden.status_code == 404


def test_runner_live_shape_does_not_reuse_or_duplicate_and_deletes(monkeypatch):
    monkeypatch.setattr("app.imaging.detect_faces", lambda image: [FaceBox(120, 100, 360, 420)])
    client = _client("user-a")
    client.post("/v1/consents", json={"external_processing": True, "retention_acknowledged": True})
    product = client.post(
        "/v1/products",
        json={
            "name": "Example Cleanser",
            "source_url": "https://example.com/cleanser",
            "image_rights": "I photographed packaging I own.",
            "price": "16.99",
            "currency": "USD",
            "ingredient_label": "water, glycerin",
            "source_observed_at": "2026-11-01T00:00:00+00:00",
            "confirmed": True,
            "mappings": [
                {
                    "concern": "redness",
                    "support_note": "The source page discusses redness and the label lists glycerin.",
                    "source_url": "https://example.com/cleanser",
                    "reviewer_confirmed": True,
                }
            ],
        },
    )
    assert product.status_code == 200
    uploaded = client.post("/v1/assets", files={"file": ("selfie.png", _png(), "image/png")})
    created = client.post(
        "/v1/experiments",
        json={
            "asset_id": uploaded.json()["id"],
            "concerns": ["texture", "pore", "redness", "oiliness", "moisture", "acne", "age_spot"],
            "product_ids": [product.json()["id"]],
            "priorities": {"redness": 2},
        },
    )
    experiment_id = created.json()["experiment_id"]
    session = session_factory()()
    fake = FakeYouCam()
    storage = LocalStorage(get_settings().local_storage_dir)
    action = "wait"
    for _ in range(40):
        action, _delay = advance_experiment(session, storage, fake, get_settings(), experiment_id)
        if action == "done":
            break
    assert action == "done"
    assert len(fake.created) == 7
    before = len(fake.created)
    action, _delay = advance_experiment(session, storage, fake, get_settings(), experiment_id)
    assert action == "done"
    assert len(fake.created) == before
    payload = client.get(f"/v1/experiments/{experiment_id}").json()
    assert payload["status"] == "completed"
    assert payload["summary"]["label"] in {
        "recommendation_changed",
        "stable_under_tested_transformations",
        "insufficient_evidence",
    }
    assert payload["counts"]["submitted"] == 7
    assert payload["counts"]["accepted_variants"] == 6
    assert payload["counts"]["provider_failed"] == 0
    texture_cells = [cell for cell in payload["sensitivity"]["cells"] if cell["concern"] == "texture"]
    assert all(cell["delta"] is not None for cell in texture_cells)
    assert fake.downloads == 7
    metadata = payload["variants"][1]["provider"]["metadata"]
    assert "https://" not in str(metadata)
    assert "mask_urls" not in metadata
    deleted = client.delete(f"/v1/experiments/{experiment_id}")
    assert deleted.status_code == 200
    assert client.get(f"/v1/experiments/{experiment_id}").status_code == 404
    session.close()


def test_baseline_rejection_stops_variants_and_ambiguous_task_is_not_duplicated(monkeypatch):
    monkeypatch.setattr("app.imaging.detect_faces", lambda image: [FaceBox(120, 100, 360, 420)])
    client = _client("user-a")
    client.post("/v1/consents", json={"external_processing": True, "retention_acknowledged": True})
    uploaded = client.post("/v1/assets", files={"file": ("selfie.png", _png(), "image/png")})
    created = client.post("/v1/experiments", json={"asset_id": uploaded.json()["id"], "concerns": ["texture"]})
    experiment_id = created.json()["experiment_id"]
    session = session_factory()()
    storage = LocalStorage(get_settings().local_storage_dir)
    fake = FakeYouCam(fail_baseline=True)
    action = "wait"
    for _ in range(10):
        action, _delay = advance_experiment(session, storage, fake, get_settings(), experiment_id)
        if action == "done":
            break
    experiment = session.get(Experiment, experiment_id)
    assert experiment.status == "baseline_rejected"
    assert session.query(ProviderTask).filter(ProviderTask.provider_task_id.is_not(None)).count() == 0
    variants = session.query(Variant).filter_by(experiment_id=experiment_id, role="variant").all()
    assert variants
    assert all(item.status == "not_submitted" for item in variants)
    session.close()

    client = _client("user-a")
    client.post("/v1/consents", json={"external_processing": True, "retention_acknowledged": True})
    uploaded = client.post("/v1/assets", files={"file": ("selfie.png", _png(), "image/png")})
    created = client.post("/v1/experiments", json={"asset_id": uploaded.json()["id"], "concerns": ["texture"]})
    experiment_id = created.json()["experiment_id"]
    session = session_factory()()
    fake = FakeYouCam(ambiguous_on=1)
    for _ in range(15):
        action, _delay = advance_experiment(session, storage, fake, get_settings(), experiment_id)
        if action == "done":
            break
    experiment = session.get(Experiment, experiment_id)
    assert experiment.status == "needs_reconciliation"
    created_count = len(fake.created)
    advance_experiment(session, storage, fake, get_settings(), experiment_id)
    assert len(fake.created) == created_count
    session.close()


def test_quota_blocks_when_cap_is_below_the_estimate(monkeypatch):
    monkeypatch.setattr("app.imaging.detect_faces", lambda image: [FaceBox(120, 100, 360, 420)])
    settings = get_settings()
    original = settings.youcam_user_daily_unit_cap
    settings.youcam_user_daily_unit_cap = 10
    try:
        client = _client("user-a")
        client.post("/v1/consents", json={"external_processing": True, "retention_acknowledged": True})
        uploaded = client.post("/v1/assets", files={"file": ("selfie.png", _png(), "image/png")})
        response = client.post("/v1/experiments", json={"asset_id": uploaded.json()["id"]})
        assert response.status_code == 429
        assert response.json()["error"]["code"] == "user_daily_cap"
    finally:
        settings.youcam_user_daily_unit_cap = original


def test_pricing_missing_blocks_plan():
    settings = get_settings()
    original = settings.youcam_unit_cost_per_task
    settings.youcam_unit_cost_per_task = ""
    try:
        client = _client("user-a")
        response = client.post("/v1/experiments/plan", json={})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "pricing_unconfigured"
    finally:
        settings.youcam_unit_cost_per_task = original


def test_account_deletion_removes_only_that_owner(monkeypatch):
    monkeypatch.setattr("app.imaging.detect_faces", lambda image: [FaceBox(120, 100, 360, 420)])
    client = _client("user-a")
    client.post("/v1/consents", json={"external_processing": True, "retention_acknowledged": True})
    client.post("/v1/assets", files={"file": ("selfie.png", _png(), "image/png")})
    session = session_factory()()
    session.add(
        Asset(
            id=str(uuid.uuid4()),
            owner_id="user-b",
            kind="capture",
            storage_path="user-b/capture/x.png",
            content_type="image/png",
            sha256="abc",
            byte_size=1,
        )
    )
    session.commit()
    assert client.delete("/v1/account").status_code == 200
    assert session.query(Asset).filter_by(owner_id="user-a").count() == 0
    assert session.query(Asset).filter_by(owner_id="user-b").count() == 1
    assert session.query(Job).filter_by(owner_id="user-a").count() == 0
    session.close()
