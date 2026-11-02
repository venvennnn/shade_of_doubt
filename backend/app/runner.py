"""Advance one experiment or recapture without duplicating an ambiguous paid task."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy.orm import Session

from app.analysis import (
    colour_derivative,
    decision_label,
    direction_block,
    exposure_derivative,
    paired_delta,
    summarise_deltas,
)
from app.config import (
    COLOUR_CONVERSION,
    ENCODE_METHOD,
    PIPELINE_VERSION,
    RESIZE_METHOD,
    SCORE_DIRECTION_SOURCE,
    Settings,
)
from app.errors import ProviderError
from app.imaging import render_master, render_variants, sha256_bytes
from app.models import (
    Asset,
    ConcernScore,
    Experiment,
    ProviderTask,
    RankingSnapshot,
    RecaptureSession,
    Variant,
    ensure_utc,
    utcnow,
)
from app.quotas import release_units
from app.ranking import compare_rankings, formula_document, rank_products
from app.storage import Storage
from app.youcam import YouCamClient, primary_score, safe_task_metadata

BASELINE_IMAGE_ERRORS = {
    "error_no_face",
    "error_decode_image",
    "error_src_face_too_small",
    "error_src_face_out_of_bound",
    "error_lighting_dark",
    "error_pose",
    "error_face_parsing",
    "error_below_min_image_size",
    "error_exceed_max_image_size",
    "exceed_max_filesize",
    "error_nsfw_content_detected",
}


def _new_id() -> str:
    return str(uuid.uuid4())


def _store_bytes(session: Session, storage: Storage, owner_id: str, kind: str, data: bytes, width: int, height: int) -> Asset:
    asset = Asset(
        id=_new_id(),
        owner_id=owner_id,
        kind=kind,
        storage_path=f"{owner_id}/{kind}/{_new_id()}.png",
        content_type="image/png",
        sha256=sha256_bytes(data),
        byte_size=len(data),
        width=width,
        height=height,
    )
    storage.put(asset.storage_path, data, "image/png")
    session.add(asset)
    session.flush()
    return asset


def _release_variant(session: Session, settings: Settings, variant: Variant) -> None:
    if variant.unit_state == "released":
        return
    cost = settings.unit_cost or 0
    release_units(
        session,
        settings,
        variant.owner_id,
        variant.experiment_id,
        cost,
        note=f"release variant {variant.id}",
    )
    variant.unit_state = "released"


def _inflight(session: Session) -> int:
    return (
        session.query(ProviderTask)
        .filter(ProviderTask.status.in_(["submitting", "running"]))
        .count()
    )


def _generate(session: Session, storage: Storage, settings: Settings, experiment: Experiment) -> str:
    experiment.stage = "generating"
    baseline = (
        session.query(Variant)
        .filter(Variant.experiment_id == experiment.id, Variant.role == "baseline")
        .one()
    )
    if baseline.asset_id:
        experiment.stage = "submitting"
        return "ready"
    capture = session.get(Asset, experiment.asset_id)
    raw = storage.get(capture.storage_path)
    master, master_png = render_master(raw, settings.normalize_long_side)
    if len(master_png) > settings.max_provider_bytes:
        experiment.status = "failed"
        experiment.stage = "failed"
        experiment.error_code = "encoded_too_large"
        experiment.error_message = "The normalised PNG exceeds the documented 10MB provider file limit."
        for variant in session.query(Variant).filter_by(experiment_id=experiment.id):
            _release_variant(session, settings, variant)
        return "stopped"
    asset = _store_bytes(session, storage, experiment.owner_id, "baseline", master_png, master.width, master.height)
    baseline.asset_id = asset.id
    baseline.status = "generated"
    baseline.sha256 = asset.sha256
    baseline.width = master.width
    baseline.height = master.height
    baseline.clipping_fraction = 0.0
    face = (capture.validation_json or {}).get("face") or {}
    # The stored face box was measured on this same normalised image at upload.
    face_box = None
    if face:
        face_box = (int(face["x"]), int(face["y"]), int(face["width"]), int(face["height"]))
    plan = [item for item in experiment.config_json["plan"]]
    rendered = render_variants(master, plan, settings, face_box)
    rows = {
        row.key: row
        for row in session.query(Variant).filter(Variant.experiment_id == experiment.id, Variant.role == "variant")
    }
    for item in rendered:
        row = rows[item.key]
        row.crop_bounds_json = item.crop_bounds
        row.clipping_fraction = item.clipping_fraction
        row.sha256 = item.sha256
        row.width = item.width
        row.height = item.height
        if item.status == "rejected_local":
            row.status = "rejected_local"
            row.rejection_reason = item.rejection_reason
            _release_variant(session, settings, row)
            continue
        variant_asset = _store_bytes(
            session, storage, experiment.owner_id, "variant", item.png_bytes, item.width, item.height
        )
        row.asset_id = variant_asset.id
        row.status = "generated"
    experiment.stage = "submitting"
    session.flush()
    return "ready"


def _persist_scores(
    session: Session,
    storage: Storage,
    client: YouCamClient,
    owner_id: str,
    experiment_id: str,
    provider_row: ProviderTask,
    parsed,
    variant_id: str | None,
    recapture_id: str | None,
    concerns: list[str],
) -> None:
    session.query(ConcernScore).filter(ConcernScore.provider_task_id == provider_row.id).delete()
    for item in parsed.scores:
        overlay_id = None
        if item.mask_urls:
            try:
                blob = client.download(item.mask_urls[0])
                overlay = _store_bytes(session, storage, owner_id, "overlay", blob, 0, 0)
                overlay_id = overlay.id
            except ProviderError:
                overlay_id = None
        session.add(
            ConcernScore(
                id=_new_id(),
                owner_id=owner_id,
                experiment_id=experiment_id,
                variant_id=variant_id,
                recapture_session_id=recapture_id,
                provider_task_id=provider_row.id,
                concern=item.concern,
                region=item.region,
                raw_score=item.raw_score,
                ui_score=item.ui_score,
                general_score=item.general_score,
                raw_available=item.raw_available,
                unavailable_reason=item.unavailable_reason,
                overlay_asset_id=overlay_id,
                is_primary=False,
            )
        )
    session.flush()
    for concern in concerns:
        chosen = primary_score(parsed.scores, concern)
        rows = session.query(ConcernScore).filter_by(provider_task_id=provider_row.id, concern=concern).all()
        marked = False
        if chosen and chosen.raw_available:
            for row in rows:
                if row.region == chosen.region and row.raw_score == chosen.raw_score:
                    row.is_primary = True
                    marked = True
                    break
        if not marked:
            session.add(
                ConcernScore(
                    id=_new_id(),
                    owner_id=owner_id,
                    experiment_id=experiment_id,
                    variant_id=variant_id,
                    recapture_session_id=recapture_id,
                    provider_task_id=provider_row.id,
                    concern=concern,
                    region="" if chosen is None else chosen.region,
                    raw_score=None if chosen is None else chosen.raw_score,
                    ui_score=None if chosen is None else chosen.ui_score,
                    general_score=None if chosen is None else chosen.general_score,
                    raw_available=bool(chosen and chosen.raw_available),
                    unavailable_reason=(
                        None
                        if chosen and chosen.raw_available
                        else (chosen.unavailable_reason if chosen else "concern was not present in the provider payload")
                    ),
                    is_primary=True,
                )
            )
    session.flush()


def _submit_or_poll(
    session: Session,
    storage: Storage,
    client: YouCamClient,
    settings: Settings,
    experiment: Experiment,
    variant: Variant,
) -> str:
    if variant.status in {"rejected_local", "accepted", "provider_failed"}:
        return "terminal"
    task = session.query(ProviderTask).filter_by(variant_id=variant.id).one_or_none()
    if task and task.status == "needs_reconciliation":
        return "reconcile"
    if task is None:
        if _inflight(session) >= settings.youcam_max_concurrency:
            return "wait"
        task = ProviderTask(
            id=_new_id(),
            owner_id=variant.owner_id,
            experiment_id=experiment.id,
            variant_id=variant.id,
            status="submitting",
            submit_started_at=utcnow(),
            safe_metadata_json={"phase": "submitting"},
        )
        session.add(task)
        variant.status = "submitting"
        session.commit()
        asset = session.get(Asset, variant.asset_id)
        data = storage.get(asset.storage_path)
        try:
            file_id = client.register_and_upload(f"{variant.key}.png", "image/png", data)
            provider_id = client.create_task(file_id, experiment.config_json["concerns"])
        except ProviderError as exc:
            task.error_code = exc.code
            task.error_message = exc.message
            task.http_status = exc.http_status
            if exc.ambiguous:
                task.status = "needs_reconciliation"
                variant.status = "needs_reconciliation"
                session.commit()
                return "reconcile"
            task.status = "error"
            variant.status = "provider_failed"
            variant.rejection_reason = exc.message
            _release_variant(session, settings, variant)
            session.commit()
            return "failed"
        task.file_id = file_id
        task.provider_task_id = provider_id
        task.status = "running"
        task.submitted_at = utcnow()
        variant.status = "running"
        session.commit()
        return "wait"
    if not task.provider_task_id:
        task.status = "needs_reconciliation"
        variant.status = "needs_reconciliation"
        task.error_code = "ambiguous_submission"
        task.error_message = "A previous attempt started submission and did not record a task id."
        session.commit()
        return "reconcile"
    try:
        parsed = client.get_task(task.provider_task_id)
    except ProviderError as exc:
        task.poll_count += 1
        task.error_code = exc.code
        task.error_message = exc.message
        session.commit()
        return "wait"
    task.poll_count += 1
    task.safe_metadata_json = {**safe_task_metadata(parsed), "retry_after_seconds": parsed.retry_after_seconds}
    task.schema_version = parsed.schema_version
    delay_status = parsed.task_status in {"", "running"} or parsed.retry_after_seconds
    submitted_at = ensure_utc(task.submitted_at)
    timed_out = submitted_at is not None and utcnow() - submitted_at > timedelta(seconds=settings.youcam_task_timeout_seconds)
    if delay_status and not (parsed.task_status == "error"):
        if timed_out and parsed.task_status != "success":
            task.status = "error"
            task.error_code = "poll_timeout"
            task.error_message = "Polling exceeded the configured timeout before YouCam reported success or error."
            variant.status = "provider_failed"
            variant.rejection_reason = task.error_message
            _release_variant(session, settings, variant)
            session.commit()
            return "failed"
        task.status = "running"
        variant.status = "running"
        experiment.stage = "polling"
        session.commit()
        return "wait"
    if parsed.task_status == "success":
        _persist_scores(
            session,
            storage,
            client,
            variant.owner_id,
            experiment.id,
            task,
            parsed,
            variant.id,
            None,
            experiment.config_json["concerns"],
        )
        task.status = "success"
        task.completed_at = utcnow()
        task.error_code = None
        variant.status = "accepted"
        variant.unit_state = "estimated"
        session.commit()
        return "terminal"
    task.status = "error"
    task.error_code = parsed.error_code or "provider_error"
    task.error_message = parsed.error_message
    task.completed_at = utcnow()
    variant.status = "provider_failed"
    variant.rejection_reason = task.error_message or task.error_code
    _release_variant(session, settings, variant)
    session.commit()
    return "failed"


def _finalise(session: Session, settings: Settings, experiment: Experiment) -> None:
    experiment.stage = "finalising"
    assembled = assemble_experiment(session, experiment)
    experiment.summary_json = assembled["summary"]
    experiment.status = "completed"
    experiment.stage = "completed"
    experiment.completed_at = utcnow()
    existing = session.query(RankingSnapshot).filter_by(experiment_id=experiment.id).one_or_none()
    if existing is None:
        session.add(
            RankingSnapshot(
                id=_new_id(),
                experiment_id=experiment.id,
                owner_id=experiment.owner_id,
                rule_version_id=experiment.rule_version_id or "",
                catalogue_json=experiment.config_json.get("catalogue") or {"products": []},
                result_json=assembled["ranking"],
            )
        )
    session.flush()


def advance_experiment(session: Session, storage: Storage, client: YouCamClient, settings: Settings, experiment_id: str) -> tuple[str, float]:
    experiment = session.get(Experiment, experiment_id)
    if experiment is None:
        return "done", 0
    if experiment.status in {"completed", "failed", "baseline_rejected", "needs_reconciliation"}:
        return "done", 0
    if experiment.stage in {"queued", "generating"} or not _baseline(session, experiment).asset_id:
        outcome = _generate(session, storage, settings, experiment)
        session.commit()
        if outcome == "stopped":
            return "done", 0
    baseline = _baseline(session, experiment)
    if baseline.status != "accepted":
        outcome = _submit_or_poll(session, storage, client, settings, experiment, baseline)
        if outcome == "wait":
            return "wait", _pending_delay(session, settings, experiment)
        if outcome == "reconcile":
            _stop_unsubmitted(session, settings, experiment)
            experiment.status = "needs_reconciliation"
            experiment.stage = "needs_reconciliation"
            experiment.error_message = "Baseline submission was ambiguous and was not duplicated."
            session.commit()
            return "done", 0
        if baseline.status != "accepted":
            _stop_unsubmitted(session, settings, experiment)
            task = session.query(ProviderTask).filter_by(variant_id=baseline.id).one_or_none()
            image_problem = bool(task and task.error_code in BASELINE_IMAGE_ERRORS)
            experiment.status = "baseline_rejected" if image_problem else "failed"
            experiment.stage = experiment.status
            experiment.error_code = None if task is None else task.error_code
            experiment.error_message = (
                "YouCam rejected the unmodified baseline. Submit a new capture; variant tasks were not sent."
                if image_problem
                else (baseline.rejection_reason or "Baseline submission failed.")
            )
            experiment.completed_at = utcnow()
            session.commit()
            return "done", 0
    variants = (
        session.query(Variant)
        .filter(Variant.experiment_id == experiment.id, Variant.role == "variant")
        .order_by(Variant.sort_order)
        .all()
    )
    waiting = False
    for variant in variants:
        outcome = _submit_or_poll(session, storage, client, settings, experiment, variant)
        if outcome == "reconcile":
            _stop_unsubmitted(session, settings, experiment)
            experiment.status = "needs_reconciliation"
            experiment.stage = "needs_reconciliation"
            experiment.error_message = f"Variant {variant.key} was ambiguous and was not duplicated."
            session.commit()
            return "done", 0
        if outcome == "wait":
            waiting = True
            break
    session.refresh(experiment)
    variants = (
        session.query(Variant)
        .filter(Variant.experiment_id == experiment.id, Variant.role == "variant")
        .all()
    )
    if waiting or any(item.status in {"generated", "pending", "submitting", "running"} for item in variants):
        experiment.stage = "polling" if waiting else "submitting"
        session.commit()
        return "wait", _pending_delay(session, settings, experiment)
    _finalise(session, settings, experiment)
    session.commit()
    return "done", 0


def advance_recapture(session: Session, storage: Storage, client: YouCamClient, settings: Settings, recapture_id: str) -> tuple[str, float]:
    recapture = session.get(RecaptureSession, recapture_id)
    if recapture is None or recapture.status in {"completed", "failed", "needs_reconciliation"}:
        return "done", 0
    experiment = session.get(Experiment, recapture.experiment_id)
    task = session.query(ProviderTask).filter_by(recapture_session_id=recapture.id).one_or_none()
    asset = session.get(Asset, recapture.asset_id)
    if task is None:
        master, master_png = render_master(storage.get(asset.storage_path), settings.normalize_long_side)
        if len(master_png) > settings.max_provider_bytes:
            recapture.status = "failed"
            recapture.error_message = "Normalised recapture exceeds 10MB."
            release_units(session, settings, recapture.owner_id, experiment.id, settings.unit_cost or 0, f"release recapture {recapture.id}")
            session.commit()
            return "done", 0
        storage.put(asset.storage_path, master_png, "image/png")
        asset.sha256 = sha256_bytes(master_png)
        asset.width = master.width
        asset.height = master.height
        asset.byte_size = len(master_png)
        if _inflight(session) >= settings.youcam_max_concurrency:
            return "wait", settings.youcam_poll_interval_seconds
        task = ProviderTask(
            id=_new_id(),
            owner_id=recapture.owner_id,
            experiment_id=experiment.id,
            recapture_session_id=recapture.id,
            status="submitting",
            submit_started_at=utcnow(),
        )
        session.add(task)
        session.commit()
        try:
            data = storage.get(asset.storage_path)
            file_id = client.register_and_upload("recapture.png", "image/png", data)
            task.provider_task_id = client.create_task(file_id, experiment.config_json["concerns"])
            task.file_id = file_id
            task.status = "running"
            task.submitted_at = utcnow()
            recapture.status = "running"
            session.commit()
            return "wait", settings.youcam_poll_interval_seconds
        except ProviderError as exc:
            task.error_code = exc.code
            task.error_message = exc.message
            if exc.ambiguous:
                task.status = "needs_reconciliation"
                recapture.status = "needs_reconciliation"
            else:
                task.status = "error"
                recapture.status = "failed"
                recapture.error_message = exc.message
                release_units(session, settings, recapture.owner_id, experiment.id, settings.unit_cost or 0, f"release recapture {recapture.id}")
            session.commit()
            return "done", 0
    if not task.provider_task_id:
        task.status = "needs_reconciliation"
        recapture.status = "needs_reconciliation"
        session.commit()
        return "done", 0
    parsed = client.get_task(task.provider_task_id)
    task.poll_count += 1
    task.safe_metadata_json = safe_task_metadata(parsed)
    if parsed.task_status in {"", "running"}:
        task.status = "running"
        session.commit()
        return "wait", parsed.retry_after_seconds or settings.youcam_poll_interval_seconds
    if parsed.task_status == "success":
        _persist_scores(
            session,
            storage,
            client,
            recapture.owner_id,
            experiment.id,
            task,
            parsed,
            None,
            recapture.id,
            experiment.config_json["concerns"],
        )
        task.status = "success"
        task.completed_at = utcnow()
        recapture.status = "completed"
        recapture.completed_at = utcnow()
        session.commit()
        return "done", 0
    task.status = "error"
    task.error_code = parsed.error_code
    task.error_message = parsed.error_message
    recapture.status = "failed"
    recapture.error_message = parsed.error_message
    release_units(session, settings, recapture.owner_id, experiment.id, settings.unit_cost or 0, f"release recapture {recapture.id}")
    session.commit()
    return "done", 0


def _baseline(session: Session, experiment: Experiment) -> Variant:
    return session.query(Variant).filter_by(experiment_id=experiment.id, role="baseline").one()


def _stop_unsubmitted(session: Session, settings: Settings, experiment: Experiment) -> None:
    for variant in session.query(Variant).filter_by(experiment_id=experiment.id):
        if variant.status in {"pending", "generated"}:
            variant.status = "not_submitted"
            _release_variant(session, settings, variant)


def _pending_delay(session: Session, settings: Settings, experiment: Experiment) -> float:
    delays = [settings.youcam_poll_interval_seconds]
    tasks = session.query(ProviderTask).filter_by(experiment_id=experiment.id).all()
    for task in tasks:
        raw = (task.safe_metadata_json or {}).get("retry_after_seconds")
        if raw:
            delays.append(float(raw))
    return max(delays)


def _raw_map(session: Session, variant_id: str | None = None, recapture_id: str | None = None) -> dict[str, dict]:
    query = session.query(ConcernScore).filter(ConcernScore.is_primary.is_(True))
    if variant_id:
        query = query.filter(ConcernScore.variant_id == variant_id)
    if recapture_id:
        query = query.filter(ConcernScore.recapture_session_id == recapture_id)
    found = {}
    for row in query:
        found[row.concern] = {
            "raw_score": row.raw_score,
            "ui_score": row.ui_score,
            "general_score": row.general_score,
            "raw_available": row.raw_available,
            "unavailable_reason": row.unavailable_reason,
            "region": row.region,
            "overlay_asset_id": row.overlay_asset_id,
        }
    return found


def assemble_experiment(session: Session, experiment: Experiment) -> dict:
    config = experiment.config_json
    concerns = config["concerns"]
    direction = config["score_direction"]
    variants = (
        session.query(Variant).filter_by(experiment_id=experiment.id).order_by(Variant.sort_order, Variant.key).all()
    )
    tasks = {row.variant_id: row for row in session.query(ProviderTask).filter(ProviderTask.variant_id.is_not(None), ProviderTask.experiment_id == experiment.id)}
    baseline = next(item for item in variants if item.role == "baseline")
    baseline_scores = _raw_map(session, variant_id=baseline.id)
    cells = []
    ranges = []
    derivatives = []
    low = config["pipeline"]["exposure_multipliers"][0]
    high = config["pipeline"]["exposure_multipliers"][1]
    gains = config["pipeline"]["channel_gains"]
    for concern in concerns:
        points = []
        point_details = []
        raw_low = raw_high = raw_warm = raw_cool = None
        for variant in variants:
            if variant.role != "variant":
                continue
            scores = _raw_map(session, variant_id=variant.id)
            delta, reason = (None, "variant was not accepted")
            if variant.status == "accepted":
                delta, reason = paired_delta(
                    (scores.get(concern) or {}).get("raw_score"),
                    (baseline_scores.get(concern) or {}).get("raw_score"),
                )
            ui_delta = None
            ui_reason = None
            if variant.status == "accepted":
                ui_left = (scores.get(concern) or {}).get("ui_score")
                ui_right = (baseline_scores.get(concern) or {}).get("ui_score")
                if ui_left is None or ui_right is None:
                    ui_reason = "ui_score was absent on the baseline or this variant"
                else:
                    ui_delta = ui_left - ui_right
            else:
                ui_reason = "variant was not accepted"
            cells.append(
                {
                    "concern": concern,
                    "variant_id": variant.id,
                    "variant_key": variant.key,
                    "factor": variant.factor,
                    "delta": delta,
                    "unavailable_reason": reason,
                    "ui_delta": ui_delta,
                    "ui_unavailable_reason": ui_reason,
                    "raw_score": (scores.get(concern) or {}).get("raw_score"),
                    "ui_score": (scores.get(concern) or {}).get("ui_score"),
                    "baseline_raw_score": (baseline_scores.get(concern) or {}).get("raw_score"),
                    "baseline_ui_score": (baseline_scores.get(concern) or {}).get("ui_score"),
                }
            )
            if delta is not None:
                points.append(delta)
                point_details.append({"variant_id": variant.id, "variant_key": variant.key, "delta": delta})
            if variant.key == "exposure_low":
                raw_low = (scores.get(concern) or {}).get("raw_score") if variant.status == "accepted" else None
            if variant.key == "exposure_high":
                raw_high = (scores.get(concern) or {}).get("raw_score") if variant.status == "accepted" else None
            if variant.key == "colour_warm":
                raw_warm = (scores.get(concern) or {}).get("raw_score") if variant.status == "accepted" else None
            if variant.key == "colour_cool":
                raw_cool = (scores.get(concern) or {}).get("raw_score") if variant.status == "accepted" else None
        ranges.append({"concern": concern, **summarise_deltas(points), "points": point_details})
        derivatives.append({"concern": concern, **exposure_derivative(raw_high, raw_low, high, low)})
        derivatives.append(
            {
                "concern": concern,
                **colour_derivative(
                    raw_warm,
                    raw_cool,
                    gains["warm"]["red"],
                    gains["cool"]["red"],
                    gains["warm"]["blue"],
                    gains["cool"]["blue"],
                ),
            }
        )
    catalogue = config.get("catalogue", {}).get("products", [])
    priorities = config.get("priorities") or {concern: 1 for concern in concerns}
    exclusions = config.get("excluded_product_ids") or []
    ingredients = config.get("excluded_ingredients") or []
    top_k = config.get("top_k") or 3
    ranking = {"formula": formula_document(direction, top_k), "baseline": None, "variants": []}
    baseline_rank = None
    if baseline.status == "accepted":
        baseline_rank = rank_products(
            catalogue,
            {concern: (baseline_scores.get(concern) or {}).get("raw_score") for concern in concerns},
            priorities,
            direction,
            exclusions,
            ingredients,
            top_k,
        )
        ranking["baseline"] = baseline_rank
    comparable = []
    for variant in variants:
        if variant.role != "variant" or variant.status != "accepted":
            continue
        scores = _raw_map(session, variant_id=variant.id)
        ranked = rank_products(
            catalogue,
            {concern: (scores.get(concern) or {}).get("raw_score") for concern in concerns},
            priorities,
            direction,
            exclusions,
            ingredients,
            top_k,
        )
        comparison = compare_rankings(baseline_rank or {"eligible": False}, ranked, top_k)
        if comparison.get("comparable"):
            comparable.append(comparison)
        ranking["variants"].append({"variant_id": variant.id, "variant_key": variant.key, "ranking": ranked, "comparison": comparison})
    score_valid = []
    for variant in variants:
        if variant.role != "variant" or variant.status != "accepted":
            continue
        concern_cells = [cell for cell in cells if cell["variant_id"] == variant.id]
        if concern_cells and all(cell["delta"] is not None for cell in concern_cells):
            score_valid.append(variant.id)
    decision_valid = [item for item in comparable]
    top_changes = sum(1 for item in decision_valid if item["top_one_changed"])
    products_eligible = bool(baseline_rank and baseline_rank.get("eligible"))
    summary = decision_label(
        baseline_ok=baseline.status == "accepted" and any((baseline_scores.get(c) or {}).get("raw_available") for c in concerns),
        eligible_products=1 if products_eligible else 0,
        valid_variants=len(decision_valid),
        minimum_valid=config.get("minimum_valid_variants", 4),
        top_one_changes=top_changes,
        score_only=not catalogue,
    )
    if experiment.status == "running":
        summary = {
            "label": "in_progress",
            "statement": "No conclusion is shown while YouCam tasks are still running.",
            "note": "Submitted, accepted, rejected, and provider-failed counts stay separate.",
        }
    counts = {
        "planned_variants": sum(1 for item in variants if item.role == "variant"),
        "submitted": sum(1 for item in tasks.values() if item.provider_task_id),
        "accepted": sum(1 for item in variants if item.status == "accepted"),
        "rejected_local": sum(1 for item in variants if item.status == "rejected_local"),
        "provider_failed": sum(1 for item in variants if item.status == "provider_failed"),
        "needs_reconciliation": sum(1 for item in variants if item.status == "needs_reconciliation"),
        "not_submitted": sum(1 for item in variants if item.status == "not_submitted"),
    }
    # accepted includes baseline; variant accepted is separate below
    counts["accepted_variants"] = sum(1 for item in variants if item.role == "variant" and item.status == "accepted")
    counts["accepted_baseline"] = 1 if baseline.status == "accepted" else 0
    recaptures = []
    for recapture in session.query(RecaptureSession).filter_by(experiment_id=experiment.id).order_by(RecaptureSession.created_at):
        scores = _raw_map(session, recapture_id=recapture.id)
        concern_rows = []
        for concern in concerns:
            delta, reason = paired_delta(
                (scores.get(concern) or {}).get("raw_score"),
                (baseline_scores.get(concern) or {}).get("raw_score"),
            )
            synthetic = [cell["delta"] for cell in cells if cell["concern"] == concern and cell["delta"] is not None]
            concern_rows.append(
                {
                    "concern": concern,
                    "recapture_delta": delta,
                    "unavailable_reason": reason,
                    "synthetic_max_abs_delta": max((abs(value) for value in synthetic), default=None),
                    "synthetic_points": synthetic,
                }
            )
        task = session.query(ProviderTask).filter_by(recapture_session_id=recapture.id).one_or_none()
        recaptures.append(
            {
                "id": recapture.id,
                "condition": recapture.condition,
                "note": recapture.note,
                "status": recapture.status,
                "asset_id": recapture.asset_id,
                "provider_task_id": None if task is None else task.provider_task_id,
                "concerns": concern_rows,
                "created_at": recapture.created_at.isoformat(),
            }
        )
    variant_payloads = []
    for variant in variants:
        task = tasks.get(variant.id)
        variant_payloads.append(
            {
                "id": variant.id,
                "role": variant.role,
                "key": variant.key,
                "factor": variant.factor,
                "status": variant.status,
                "params": variant.params_json,
                "pipeline_version": variant.pipeline_version,
                "colour_conversion": variant.colour_conversion,
                "resize_method": variant.resize_method,
                "encode_method": variant.encode_method,
                "crop_bounds": variant.crop_bounds_json,
                "clipping_fraction": variant.clipping_fraction,
                "sha256": variant.sha256,
                "width": variant.width,
                "height": variant.height,
                "asset_id": variant.asset_id,
                "rejection_reason": variant.rejection_reason,
                "unit_state": variant.unit_state,
                "scores": _raw_map(session, variant_id=variant.id),
                "provider": None
                if task is None
                else {
                    "provider_task_id": task.provider_task_id,
                    "status": task.status,
                    "error_code": task.error_code,
                    "error_message": task.error_message,
                    "poll_count": task.poll_count,
                    "schema_version": task.schema_version,
                    "submitted_at": task.submitted_at.isoformat() if task.submitted_at else None,
                    "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                    "metadata": task.safe_metadata_json,
                },
            }
        )
    return {
        "id": experiment.id,
        "status": experiment.status,
        "stage": experiment.stage,
        "stage_label": _stage_label(experiment),
        "error_message": experiment.error_message,
        "created_at": experiment.created_at.isoformat(),
        "completed_at": experiment.completed_at.isoformat() if experiment.completed_at else None,
        "config": {
            "concerns": concerns,
            "factors": config.get("factors"),
            "pipeline": config.get("pipeline"),
            "priorities": priorities,
            "top_k": top_k,
            "minimum_valid_variants": config.get("minimum_valid_variants"),
            "score_direction": direction_block(direction),
            "score_direction_source": SCORE_DIRECTION_SOURCE,
            "excluded_ingredients": ingredients,
            "catalogue_product_ids": [item["id"] for item in catalogue],
            "guided": bool(config.get("guided")),
        },
        "counts": counts,
        "summary": {**summary, "valid_decision_variants": len(decision_valid), "valid_score_variants": len(score_valid), "counts": counts},
        "variants": variant_payloads,
        "sensitivity": {"cells": cells, "ranges": ranges, "derivatives": derivatives},
        "ranking": ranking,
        "recaptures": recaptures,
        "limitations": direction_block(direction)["limitations"]
        + [
            "Deltas describe only the tested variants.",
            "Changed in m of n is not a probability of a different capture.",
            "Provider result retention is about 24 hours; overlays are copied into private storage when a URL is actually returned.",
        ],
    }


def _stage_label(experiment: Experiment) -> str:
    labels = {
        "queued": "Waiting for a worker",
        "generating": "Generating deterministic variants",
        "submitting": "Submitting images to YouCam",
        "polling": "Polling YouCam for task status",
        "finalising": "Computing deltas from returned raw scores",
        "completed": "Provider tasks finished",
        "failed": "The run stopped before a complete result",
        "baseline_rejected": "YouCam rejected the unmodified baseline",
        "needs_reconciliation": "A submission was ambiguous and was not duplicated",
    }
    return labels.get(experiment.stage, experiment.stage)


# Imported constants kept available for tests that inspect pipeline fields on variants.
_PIPELINE_FIELDS = (PIPELINE_VERSION, COLOUR_CONVERSION, RESIZE_METHOD, ENCODE_METHOD)
