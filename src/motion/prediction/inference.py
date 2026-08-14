"""Simulator-independent single-vehicle inference and alert tracking."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Final, Protocol

import pandas as pd

from .features import observation_feature_frame
from .schema import FEATURE_NAMES, PredictionSchemaError, VehicleObservation


class PredictionModel(Protocol):
    def predict(self, features: pd.DataFrame) -> Any: ...


@dataclass(frozen=True, slots=True)
class VehiclePrediction:
    vehicle_id: str | int
    incident_detected: bool
    positive_probability: float | None = None


class VehicleRiskPredictor:
    """Apply a trusted compatible model to one vehicle observation."""

    def __init__(self, model: PredictionModel) -> None:
        feature_names = getattr(model, "feature_names_in_", None)
        if (
            feature_names is not None
            and tuple(str(value) for value in feature_names) != FEATURE_NAMES
        ):
            raise PredictionSchemaError("Model feature order is incompatible")
        self._model = model

    def predict(self, observation: VehicleObservation) -> VehiclePrediction:
        feature_frame = observation_feature_frame(observation)
        raw_prediction = self._model.predict(feature_frame)
        try:
            if len(raw_prediction) != 1:
                raise ValueError
            prediction_value = int(raw_prediction[0])
        except (IndexError, TypeError, ValueError) as error:
            raise PredictionSchemaError("Model returned an invalid prediction") from error
        if prediction_value not in {0, 1}:
            raise PredictionSchemaError("Model prediction must be binary")

        probability = self._positive_probability(feature_frame)
        return VehiclePrediction(
            vehicle_id=observation.vehicle_id,
            incident_detected=bool(prediction_value),
            positive_probability=probability,
        )

    def _positive_probability(self, features: pd.DataFrame) -> float | None:
        predict_proba = getattr(self._model, "predict_proba", None)
        classes = list(getattr(self._model, "classes_", ()))
        if not callable(predict_proba) or 1 not in classes:
            return None
        try:
            probabilities = predict_proba(features)[0]
            probability = float(probabilities[classes.index(1)])
        except (IndexError, TypeError, ValueError) as error:
            raise PredictionSchemaError("Model returned invalid probabilities") from error
        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            raise PredictionSchemaError("Positive-class probability must be between 0 and 1")
        return probability


def predict_incident(
    model: PredictionModel,
    observation: VehicleObservation,
) -> VehiclePrediction:
    """Run one simulator-independent prediction in canonical feature order."""

    return VehicleRiskPredictor(model).predict(observation)


@dataclass(frozen=True, slots=True)
class AlertPolicy:
    timeout_seconds: float = 8.0
    confirmation_brake_threshold: float = 0.8
    confirmation_speed_kmh: float = 2.0
    require_nearby_vehicle: bool = True

    def __post_init__(self) -> None:
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        if not math.isfinite(self.confirmation_brake_threshold):
            raise ValueError("confirmation_brake_threshold must be finite")
        if not 0.0 <= self.confirmation_brake_threshold <= 1.0:
            raise ValueError("confirmation_brake_threshold must be in [0, 1]")
        if not math.isfinite(self.confirmation_speed_kmh) or self.confirmation_speed_kmh < 0:
            raise ValueError("confirmation_speed_kmh must be finite and non-negative")


DEFAULT_ALERT_POLICY: Final[AlertPolicy] = AlertPolicy()


@dataclass(frozen=True, slots=True)
class ActiveAlert:
    vehicle_id: str | int
    started_at_seconds: float
    confirmed: bool = False


class AlertEventType(StrEnum):
    STARTED = "started"
    CONFIRMED = "confirmed"
    EXPIRED_FALSE_POSITIVE = "expired_false_positive"


@dataclass(frozen=True, slots=True)
class AlertEvent:
    event_type: AlertEventType
    vehicle_id: str | int
    observed_at_seconds: float
    lead_time_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class AlertTrackerState:
    active_alerts: tuple[ActiveAlert, ...] = ()
    total_alerts: int = 0
    true_positives: int = 0
    false_positives: int = 0
    lead_times_seconds: tuple[float, ...] = ()
    inference_latencies_ms: tuple[float, ...] = ()
    last_observed_at_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class AlertStatistics:
    total_alerts: int
    true_positives: int
    false_positives: int
    active_alerts: int
    precision: float | None
    mean_lead_time_seconds: float | None
    mean_inference_latency_ms: float | None


@dataclass(frozen=True, slots=True)
class TrackingSample:
    observation: VehicleObservation
    prediction: VehiclePrediction
    nearby_vehicle_count: int
    observed_at_seconds: float
    inference_latency_ms: float | None = None

    def __post_init__(self) -> None:
        if self.prediction.vehicle_id != self.observation.vehicle_id:
            raise ValueError("Prediction and observation vehicle ids differ")
        if self.nearby_vehicle_count < 0:
            raise ValueError("nearby_vehicle_count must be non-negative")
        if not math.isfinite(self.observed_at_seconds) or self.observed_at_seconds < 0:
            raise ValueError("observed_at_seconds must be finite and non-negative")
        if self.inference_latency_ms is not None and (
            not math.isfinite(self.inference_latency_ms) or self.inference_latency_ms < 0
        ):
            raise ValueError("inference_latency_ms must be finite and non-negative")


def update_alert_tracker(
    state: AlertTrackerState,
    sample: TrackingSample,
    *,
    policy: AlertPolicy = DEFAULT_ALERT_POLICY,
) -> tuple[AlertTrackerState, tuple[AlertEvent, ...]]:
    """Return a new state and events without wall-clock, I/O or global state.

    Every sample also acts as a tracker heartbeat, so alerts for vehicles no
    longer observed are expired. Confirmation is evaluated before expiry to
    preserve the legacy boundary behavior; expiry remains strict (``> 8`` by
    default), not inclusive.
    """

    now = sample.observed_at_seconds
    if state.last_observed_at_seconds is not None and now < state.last_observed_at_seconds:
        raise ValueError("Tracking samples must be processed in non-decreasing time order")

    active = {alert.vehicle_id: alert for alert in state.active_alerts}
    events: list[AlertEvent] = []
    total_alerts = state.total_alerts
    true_positives = state.true_positives
    false_positives = state.false_positives
    lead_times = state.lead_times_seconds
    latencies = state.inference_latencies_ms
    if sample.inference_latency_ms is not None:
        latencies = (*latencies, sample.inference_latency_ms)

    vehicle_id = sample.observation.vehicle_id
    nearby_condition = sample.nearby_vehicle_count > 0 if policy.require_nearby_vehicle else True
    if sample.prediction.incident_detected and nearby_condition and vehicle_id not in active:
        active[vehicle_id] = ActiveAlert(
            vehicle_id=vehicle_id,
            started_at_seconds=now,
        )
        total_alerts += 1
        events.append(
            AlertEvent(
                event_type=AlertEventType.STARTED,
                vehicle_id=vehicle_id,
                observed_at_seconds=now,
            )
        )

    current_alert = active.get(vehicle_id)
    if (
        current_alert is not None
        and not current_alert.confirmed
        and sample.observation.brake > policy.confirmation_brake_threshold
        and sample.observation.speed_kmh < policy.confirmation_speed_kmh
    ):
        lead_time = now - current_alert.started_at_seconds
        current_alert = replace(current_alert, confirmed=True)
        active[vehicle_id] = current_alert
        true_positives += 1
        lead_times = (*lead_times, lead_time)
        events.append(
            AlertEvent(
                event_type=AlertEventType.CONFIRMED,
                vehicle_id=vehicle_id,
                observed_at_seconds=now,
                lead_time_seconds=lead_time,
            )
        )

    for alert_id, alert in tuple(active.items()):
        if now - alert.started_at_seconds <= policy.timeout_seconds:
            continue
        if not alert.confirmed:
            false_positives += 1
            events.append(
                AlertEvent(
                    event_type=AlertEventType.EXPIRED_FALSE_POSITIVE,
                    vehicle_id=alert_id,
                    observed_at_seconds=now,
                )
            )
        del active[alert_id]

    next_state = AlertTrackerState(
        active_alerts=tuple(sorted(active.values(), key=lambda item: str(item.vehicle_id))),
        total_alerts=total_alerts,
        true_positives=true_positives,
        false_positives=false_positives,
        lead_times_seconds=lead_times,
        inference_latencies_ms=latencies,
        last_observed_at_seconds=now,
    )
    return next_state, tuple(events)


def alert_statistics(state: AlertTrackerState) -> AlertStatistics:
    precision = state.true_positives / state.total_alerts if state.total_alerts else None
    mean_lead_time = (
        sum(state.lead_times_seconds) / len(state.lead_times_seconds)
        if state.lead_times_seconds
        else None
    )
    mean_latency = (
        sum(state.inference_latencies_ms) / len(state.inference_latencies_ms)
        if state.inference_latencies_ms
        else None
    )
    return AlertStatistics(
        total_alerts=state.total_alerts,
        true_positives=state.true_positives,
        false_positives=state.false_positives,
        active_alerts=len(state.active_alerts),
        precision=precision,
        mean_lead_time_seconds=mean_lead_time,
        mean_inference_latency_ms=mean_latency,
    )
