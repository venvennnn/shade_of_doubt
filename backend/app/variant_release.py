from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Experiment, Variant
from app.quotas import release_units


def release_pending(session: Session, settings: Settings, experiment: Experiment) -> None:
    cost = settings.unit_cost or 0
    for variant in session.query(Variant).filter_by(experiment_id=experiment.id):
        if variant.unit_state == "released":
            continue
        if variant.status in {"accepted"} or variant.unit_state == "estimated":
            continue
        release_units(session, settings, experiment.owner_id, experiment.id, cost, f"release unfinished {variant.id}")
        variant.unit_state = "released"
