from __future__ import annotations

import pytest

from motion.prediction.inference import (
    AlertEventType,
    AlertTrackerState,
    TrackingSample,
    VehiclePrediction,
    alert_statistics,
    predict_incident,
    update_alert_tracker,
)
from motion.prediction.schema import MODEL_FEATURES, VehicleObservation


class RecordingModel:
    feature_names_in_ = MODEL_FEATURES
    classes_ = (0, 1)

    def __init__(self, prediction: int = 1) -> None:
        self.prediction = prediction
        self.observed_columns: tuple[str, ...] = ()

    def predict(self, features):
        self.observed_columns = tuple(features.columns)
        return [self.prediction]

    def predict_proba(self, _features):
        return [[0.25, 0.75]]


def _observation(
    vehicle_id: str,
    *,
    speed_kmh: float = 10.0,
    brake: float = 0.0,
) -> VehicleObservation:
    return VehicleObservation(
        vehicle_id=vehicle_id,
        speed_kmh=speed_kmh,
        throttle=0.2,
        brake=brake,
        steer=0.0,
        weather_rain=0.0,
    )


def _sample(
    vehicle_id: str,
    *,
    now: float,
    risk: bool,
    nearby: int = 1,
    speed_kmh: float = 10.0,
    brake: float = 0.0,
    latency_ms: float | None = None,
) -> TrackingSample:
    observation = _observation(vehicle_id, speed_kmh=speed_kmh, brake=brake)
    return TrackingSample(
        observation=observation,
        prediction=VehiclePrediction(vehicle_id, risk),
        nearby_vehicle_count=nearby,
        observed_at_seconds=now,
        inference_latency_ms=latency_ms,
    )


def test_single_vehicle_predictor_preserves_feature_order_and_probability() -> None:
    model = RecordingModel()

    result = predict_incident(model, _observation("vehicle"))

    assert result.incident_detected is True
    assert result.positive_probability == 0.75
    assert model.observed_columns == MODEL_FEATURES


def test_predictor_propagates_model_failure() -> None:
    class FailingModel(RecordingModel):
        def predict(self, _features):
            raise RuntimeError("estimator failed")

    with pytest.raises(RuntimeError, match="estimator failed"):
        predict_incident(FailingModel(), _observation("vehicle"))


def test_tracker_opens_deduplicates_and_confirms_without_mutating_input() -> None:
    original = AlertTrackerState()
    started, events = update_alert_tracker(
        original,
        _sample("a", now=0, risk=True, latency_ms=2.0),
    )
    duplicate, duplicate_events = update_alert_tracker(
        started,
        _sample("a", now=1, risk=True),
    )
    confirmed, confirmation_events = update_alert_tracker(
        duplicate,
        _sample("a", now=2, risk=False, speed_kmh=1.9, brake=0.81),
    )

    assert original == AlertTrackerState()
    assert [event.event_type for event in events] == [AlertEventType.STARTED]
    assert duplicate_events == ()
    assert [event.event_type for event in confirmation_events] == [AlertEventType.CONFIRMED]
    assert confirmed.total_alerts == 1
    assert confirmed.true_positives == 1
    assert confirmed.lead_times_seconds == (2,)
    assert alert_statistics(confirmed).mean_inference_latency_ms == 2.0


def test_tracker_requires_nearby_vehicle_to_open() -> None:
    state, events = update_alert_tracker(
        AlertTrackerState(),
        _sample("a", now=0, risk=True, nearby=0),
    )

    assert state.total_alerts == 0
    assert events == ()


def test_tracker_expiry_is_strict_and_expires_disappeared_vehicle() -> None:
    started, _ = update_alert_tracker(
        AlertTrackerState(),
        _sample("a", now=0, risk=True),
    )
    at_boundary, boundary_events = update_alert_tracker(
        started,
        _sample("heartbeat", now=8.0, risk=False),
    )
    expired, events = update_alert_tracker(
        at_boundary,
        _sample("heartbeat", now=8.001, risk=False),
    )

    assert len(at_boundary.active_alerts) == 1
    assert boundary_events == ()
    assert [event.event_type for event in events] == [AlertEventType.EXPIRED_FALSE_POSITIVE]
    assert expired.false_positives == 1
    assert expired.active_alerts == ()
