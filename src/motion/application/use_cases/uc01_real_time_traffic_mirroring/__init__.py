"""UC-01: real-time traffic mirroring."""

from ..descriptor import UseCaseDescriptor, UseCaseStatus

USE_CASE = UseCaseDescriptor(
    use_case_id="UC-01",
    name="Real-Time Traffic Mirroring",
    layer="Simulation",
    status=UseCaseStatus.IMPLEMENTED,
    goal="Replicate observed road traffic in CARLA as a synchronized traffic twin.",
    actor="Automatic system",
    evidence=(
        "motion.domain.devices defines timestamped device count and speed readings and maps device IDs to coordinates.",
        "motion.infrastructure.here acquires and parses flow, jam, incident, closure, confidence, and segment geometry data.",
        "The UC-01 service projects geographic data, derives vehicle populations, and drives the explicit CARLA simulator port.",
        "The installed motion CLI exposes map provisioning and real-time mirroring.",
    ),
    dependencies=(
        "Field-device feed and device-to-coordinate registry",
        "HERE Traffic flow and incident data",
        "OpenStreetMap/OpenDRIVE map provisioning and geographic calibration",
        "CARLA simulator and TrafficManager",
    ),
    missing_behavior=(
        "No repository evidence was found for the governance dashboard associated with the final presentation step.",
        "The current field-device adapter synthesizes readings; a live production-device ingestion contract is not evidenced.",
    ),
    document_references=("MOTION / OR3 / UC-01",),
)

__all__ = ["USE_CASE"]
