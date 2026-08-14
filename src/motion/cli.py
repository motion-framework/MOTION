"""Single composition root and user-facing command-line interface."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from motion.config.runtime_state import (
    ActiveMapState,
    ActiveMapStateRepository,
    RuntimeStateError,
    load_active_map_state,
)
from motion.config.settings import AppSettings, SettingsError, load_settings
from motion.domain.geography import DEFAULT_CENTER_RADIUS_METERS, BoundingBox

if TYPE_CHECKING:
    from motion.application.map_provisioning import (
        MapProvisioningService,
        ProvisioningResult,
    )
    from motion.domain.maps import MapProfile
    from motion.ports.traffic import TrafficDataProvider

LOGGER = logging.getLogger("motion")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="motion",
        description="MOTION mobility, simulation, data, and prediction tools.",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    uc_status = subcommands.add_parser(
        "uc-status", help="Show implementation status for Macro UC-01 through UC-07."
    )
    uc_status.add_argument("--json", action="store_true", dest="as_json")
    uc_status.set_defaults(handler=_handle_uc_status)

    map_parser = subcommands.add_parser("map", help="Provision and inspect maps.")
    map_commands = map_parser.add_subparsers(dest="map_command", required=True)

    provision = map_commands.add_parser(
        "provision", help="Download, convert, validate and register an OSM area."
    )
    _add_area_arguments(provision)
    provision.add_argument("--name", required=True)
    provision.set_defaults(handler=_handle_map_provision)

    mirror_road = map_commands.add_parser(
        "mirror-road", help="Select a HERE-covered road and provision its map."
    )
    mirror_road.add_argument("--lat", type=float, required=True)
    mirror_road.add_argument("--lon", type=float, required=True)
    mirror_road.add_argument("--radius", type=float, default=DEFAULT_CENTER_RADIUS_METERS)
    mirror_road.add_argument("--name", default="here_road")
    mirror_road.add_argument(
        "--geo",
        action="store_true",
        help="Use automatic road ranking instead of the interactive menu.",
    )
    mirror_road.set_defaults(handler=_handle_map_mirror_road)

    inspect = map_commands.add_parser("inspect", help="Inspect a local OSM extract.")
    inspect.add_argument("path", type=Path)
    inspect.set_defaults(handler=_handle_map_inspect)

    validate = map_commands.add_parser(
        "validate", help="Scan OpenDRIVE for supported geometry defects."
    )
    validate.add_argument("path", type=Path)
    validate.set_defaults(handler=_handle_map_validate)

    repair = map_commands.add_parser(
        "repair", help="Repair supported OpenDRIVE defects with backups."
    )
    repair.add_argument("path", type=Path)
    repair.set_defaults(handler=_handle_map_repair)

    scan_degenerate = map_commands.add_parser(
        "scan-degenerate", help="Scan only non-positive/non-numeric geometries."
    )
    scan_degenerate.add_argument("path", type=Path)
    scan_degenerate.set_defaults(handler=_handle_scan_degenerate)
    scan_overflow = map_commands.add_parser(
        "scan-overflow", help="Scan only objects positioned beyond their road."
    )
    scan_overflow.add_argument("path", type=Path)
    scan_overflow.set_defaults(handler=_handle_scan_overflow)
    patch_zero = map_commands.add_parser(
        "patch-zero", help="Patch only exactly zero-length geometries."
    )
    patch_zero.add_argument("path", type=Path)
    patch_zero.set_defaults(handler=_handle_patch_zero)
    patch_overflow = map_commands.add_parser(
        "patch-overflow", help="Clamp only objects positioned beyond their road."
    )
    patch_overflow.add_argument("path", type=Path)
    patch_overflow.set_defaults(handler=_handle_patch_overflow)

    convert = map_commands.add_parser(
        "convert-active", help="Reconvert the active OSM map to OpenDRIVE."
    )
    convert.set_defaults(handler=_handle_map_convert_active)

    mirror = subcommands.add_parser(
        "mirror", help="Run UC-01 against a provisioned or newly selected road."
    )
    mirror.add_argument("--lat", type=float)
    mirror.add_argument("--lon", type=float)
    mirror.add_argument("--radius", type=float, default=None)
    mirror.add_argument("--name", default="here_road")
    mirror.add_argument("--geo", action="store_true")
    mirror.add_argument("--skip-provision", action="store_true")
    mirror.add_argument("--carla-exe", type=Path)
    mirror.add_argument("--check-calibration", action="store_true")
    mirror.add_argument("--verify-calibration", action="store_true")
    mirror.add_argument("--once", action="store_true", help="Run one mirror tick.")
    mirror.add_argument(
        "--offline",
        action="store_true",
        help=(
            "Disable HERE/Overpass access, reuse the active map and drive UC-01 "
            "from synthetic HERE-compatible traffic and field-device observations."
        ),
    )
    mirror.set_defaults(handler=_handle_mirror)

    here_parser = subcommands.add_parser("here", help="HERE evidence tools.")
    here_commands = here_parser.add_subparsers(dest="here_command", required=True)
    verify_archive = here_commands.add_parser(
        "verify-archive", help="Verify every snapshot hash in a HERE archive."
    )
    verify_archive.add_argument("path", type=Path)
    verify_archive.set_defaults(handler=_handle_verify_archive)

    dataset = subcommands.add_parser("dataset", help="Behavioral dataset tools.")
    dataset_commands = dataset.add_subparsers(dest="dataset_command", required=True)
    build_dataset = dataset_commands.add_parser(
        "build", help="Build the enriched behavioral-analysis dataset."
    )
    build_dataset.add_argument("inputs", nargs="+", type=Path)
    build_dataset.add_argument("--output", type=Path, required=True)
    build_dataset.add_argument("--weather-rain-default", type=float)
    build_dataset.set_defaults(handler=_handle_dataset_build)

    model = subcommands.add_parser("model", help="Behavioral model tools.")
    model_commands = model.add_subparsers(dest="model_command", required=True)
    train = model_commands.add_parser("train", help="Train the fixed-contract Random Forest.")
    train.add_argument("--dataset", type=Path, required=True)
    train.add_argument("--output", type=Path)
    train.set_defaults(handler=_handle_model_train)
    infer = model_commands.add_parser("infer", help="Run real-time behavioral inference in CARLA.")
    infer.add_argument("--model", type=Path)
    infer.add_argument("--stats-output", type=Path)
    infer.set_defaults(handler=_handle_model_infer)

    telemetry = subcommands.add_parser("telemetry", help="CARLA telemetry tools.")
    telemetry_commands = telemetry.add_subparsers(dest="telemetry_command", required=True)
    collect = telemetry_commands.add_parser(
        "collect", help="Collect vehicle telemetry and collision observations."
    )
    collect.add_argument("--duration", type=float, default=180.0)
    collect.add_argument("--interval", type=float, default=0.5)
    collect.add_argument("--output", type=Path)
    collect.set_defaults(handler=_handle_telemetry_collect)

    diagnostics = subcommands.add_parser("diagnostics", help="Developer diagnostics.")
    diagnostic_commands = diagnostics.add_subparsers(dest="diagnostic_command", required=True)
    speed_units = diagnostic_commands.add_parser(
        "speed-units", help="Opt-in CARLA TrafficManager speed-unit diagnostic."
    )
    speed_units.set_defaults(handler=_handle_speed_units)
    calibration = diagnostic_commands.add_parser(
        "calibration", help="Check active-map geographic calibration in CARLA."
    )
    calibration.add_argument("--visual", action="store_true")
    calibration.set_defaults(handler=_handle_calibration)
    return parser


def _add_area_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lat", type=float)
    parser.add_argument("--lon", type=float)
    parser.add_argument("--radius", type=float, default=DEFAULT_CENTER_RADIUS_METERS)
    parser.add_argument("--sw-lat", type=float)
    parser.add_argument("--sw-lon", type=float)
    parser.add_argument("--ne-lat", type=float)
    parser.add_argument("--ne-lon", type=float)


def _bbox_from_arguments(args: argparse.Namespace) -> BoundingBox:
    center_complete = args.lat is not None and args.lon is not None
    bbox_values = (args.sw_lat, args.sw_lon, args.ne_lat, args.ne_lon)
    bbox_complete = None not in bbox_values
    if center_complete == bbox_complete:
        raise ValueError(
            "Provide either --lat/--lon (and optional --radius) or all four bbox values."
        )
    if center_complete:
        if args.radius <= 0:
            raise ValueError("--radius must be positive.")
        return BoundingBox.from_center(args.lat, args.lon, args.radius)
    return BoundingBox(*bbox_values)


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(levelname)s %(name)s: %(message)s",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    _configure_logging(args.log_level)
    try:
        settings = load_settings()
        return int(args.handler(args, settings) or 0)
    except (SettingsError, RuntimeStateError, ValueError, OSError) as error:
        parser.error(str(error))


def _handle_uc_status(args: argparse.Namespace, _settings: AppSettings) -> int:
    from motion.application.use_cases.catalog import USE_CASE_CATALOG

    if args.as_json:
        print(
            json.dumps(
                [
                    {
                        "id": descriptor.use_case_id,
                        "name": descriptor.name,
                        "status": descriptor.status.value,
                    }
                    for descriptor in USE_CASE_CATALOG
                ],
                indent=2,
            )
        )
        return 0
    for descriptor in USE_CASE_CATALOG:
        print(f"{descriptor.use_case_id}  {descriptor.status.value:<38}  {descriptor.name}")
    return 0


def _map_provisioning_service(settings: AppSettings) -> MapProvisioningService:
    from motion.application.map_provisioning import MapProvisioningService
    from motion.infrastructure.maps.artifacts import LocalMapArtifactProcessor
    from motion.infrastructure.maps.converter import (
        CarlaOsmToOpenDriveConverter,
    )
    from motion.infrastructure.osm.downloader import OsmDownloader

    return MapProvisioningService(
        downloader=OsmDownloader(
            endpoints=settings.osm.endpoints,
            contact_email=settings.osm.contact_email,
            timeout_seconds=settings.osm.request_timeout_seconds,
        ),
        converter=CarlaOsmToOpenDriveConverter(),
        artifact_processor=LocalMapArtifactProcessor(),
        state_repository=ActiveMapStateRepository(settings.paths.active_map_state),
        project_root=settings.paths.root,
    )


def _print_provisioning_result(result: ProvisioningResult) -> None:
    print(f"Active map: {result.state.name}")
    print(f"OSM:        {result.osm_path}")
    print(f"OpenDRIVE:  {result.xodr_path}")
    print(
        "Geometry:   "
        f"{result.zero_length_repair.patched_count} zero-length repair(s), "
        f"{result.object_overflow_repair.patched_count} object clamp(s)"
    )


def _handle_map_provision(args: argparse.Namespace, settings: AppSettings) -> int:
    bbox = _bbox_from_arguments(args)
    state = ActiveMapState.for_new_map(
        name=args.name,
        bbox=bbox,
        project_paths=settings.paths,
        source="direct-area",
    )
    result = _map_provisioning_service(settings).provision(state)
    _print_provisioning_result(result)
    return int(bool(result.remaining_degenerate_geometries or result.remaining_object_overflows))


def _select_and_provision_road(args: argparse.Namespace, settings: AppSettings) -> ActiveMapState:
    from motion.application.road_selection import (
        build_map_state_for_road,
        choose_road_interactively,
        group_by_road,
        representative_segment,
        segments_near_center,
        select_main_road_segment,
    )
    from motion.infrastructure.here.client import (
        HereEndpointFetcher,
        RequestsJsonTransport,
    )
    from motion.infrastructure.here.parser import TrafficParser

    if args.radius <= 0:
        raise ValueError("--radius must be positive.")
    search_bbox = BoundingBox.from_center(args.lat, args.lon, args.radius)
    fetcher = HereEndpointFetcher(
        transport=RequestsJsonTransport(),
        api_key=settings.here.api_key,
        bbox=search_bbox.to_here_bbox(),
        url=settings.here.flow_url,
        timeout_seconds=settings.here.request_timeout_seconds,
    )
    segments = TrafficParser((args.lat, args.lon)).parse(fetcher.fetch())
    if not segments:
        raise ValueError("HERE returned no traffic segments for the requested area.")
    center = (args.lat, args.lon)
    if args.geo:
        near = segments_near_center(segments, center)
        selected = select_main_road_segment(near, center)
    else:
        roads = group_by_road(segments)
        for index, road in enumerate(roads, start=1):
            print(
                f"{index:>3}  {road.name[:38]:<38} {len(road.segments):>4}  "
                f"{road.average_speed_kmh:>7.1f} km/h  "
                f"jam={road.average_jam_factor:>4.1f}"
            )
        chosen = choose_road_interactively(roads)
        selected = representative_segment(chosen.segments, center)
    state, _ = build_map_state_for_road(
        segment=selected,
        radius_meters=args.radius,
        map_name=args.name,
        project_paths=settings.paths,
    )
    result = _map_provisioning_service(settings).provision(state)
    _print_provisioning_result(result)
    return state


def _handle_map_mirror_road(args: argparse.Namespace, settings: AppSettings) -> int:
    _select_and_provision_road(args, settings)
    return 0


def _handle_map_inspect(args: argparse.Namespace, _settings: AppSettings) -> int:
    from motion.infrastructure.maps.osm_inspection import inspect_osm

    result = inspect_osm(args.path)
    print(
        f"{result.path}: nodes={result.node_count}, ways={result.way_count}, "
        f"relations={result.relation_count}"
    )
    if result.bounds:
        print(
            f"bounds ({result.bounds.source}): "
            f"SW=({result.bounds.min_lat}, {result.bounds.min_lon}) "
            f"NE=({result.bounds.max_lat}, {result.bounds.max_lon})"
        )
    return 0


def _handle_map_validate(args: argparse.Namespace, _settings: AppSettings) -> int:
    from motion.infrastructure.maps.geometry import (
        scan_degenerate_geometries,
        scan_object_overflows,
    )

    geometry_count, degenerate = scan_degenerate_geometries(args.path)
    object_count, overflows = scan_object_overflows(args.path)
    print(
        f"Scanned {geometry_count} geometries and {object_count} objects: "
        f"{len(degenerate)} degenerate, {len(overflows)} overflow."
    )
    return int(bool(degenerate or overflows))


def _handle_map_repair(args: argparse.Namespace, _settings: AppSettings) -> int:
    from motion.infrastructure.maps.geometry import (
        patch_object_overflows,
        patch_zero_length_geometries,
    )

    zero = patch_zero_length_geometries(args.path)
    overflow = patch_object_overflows(args.path)
    print(
        f"Patched {zero.patched_count} zero-length geometries and "
        f"{overflow.patched_count} overflowing objects."
    )
    return 0


def _handle_scan_degenerate(args: argparse.Namespace, _settings: AppSettings) -> int:
    from motion.infrastructure.maps.geometry import scan_degenerate_geometries

    total, problems = scan_degenerate_geometries(args.path)
    print(f"Scanned {total} <geometry> elements in {args.path}")
    for problem in problems[:25]:
        print(
            f"line {problem.line_number}: {problem.reason} "
            f"s={problem.s_position} x={problem.x_position} "
            f"y={problem.y_position} hdg={problem.heading}"
        )
    return int(bool(problems))


def _handle_scan_overflow(args: argparse.Namespace, _settings: AppSettings) -> int:
    from motion.infrastructure.maps.geometry import scan_object_overflows

    total, problems = scan_object_overflows(args.path)
    print(f"Scanned {total} <object> elements in {args.path}")
    for problem in problems[:25]:
        print(
            f"line {problem.line_number}: road id={problem.road_id} "
            f"type={problem.object_type} s={problem.object_s_position} "
            f"> length={problem.road_length}"
        )
    return int(bool(problems))


def _handle_patch_zero(args: argparse.Namespace, _settings: AppSettings) -> int:
    from motion.infrastructure.maps.geometry import patch_zero_length_geometries

    result = patch_zero_length_geometries(args.path)
    print(f"Patched {result.patched_count} zero-length <geometry> element(s).")
    return 0


def _handle_patch_overflow(args: argparse.Namespace, _settings: AppSettings) -> int:
    from motion.infrastructure.maps.geometry import patch_object_overflows

    result = patch_object_overflows(args.path)
    print(f"Patched {result.patched_count} overflowing <object> element(s).")
    return 0


def _handle_map_convert_active(_args: argparse.Namespace, settings: AppSettings) -> int:
    from motion.infrastructure.maps.converter import (
        CarlaOsmToOpenDriveConverter,
    )

    state = load_active_map_state(paths=settings.paths)
    path = CarlaOsmToOpenDriveConverter().convert(state.to_profile(settings.paths))
    print(path)
    return 0


def _handle_verify_archive(args: argparse.Namespace, _settings: AppSettings) -> int:
    from motion.infrastructure.here.archive import verify_archive

    result = verify_archive(args.path)
    print(f"Checked {result.checked_snapshots} snapshot(s): {'PASS' if result.valid else 'FAIL'}")
    for error in result.errors:
        print(f"- {error}")
    return int(not result.valid)


def _handle_mirror(args: argparse.Namespace, settings: AppSettings) -> int:
    if args.offline:
        if any(value is not None for value in (args.lat, args.lon, args.radius)) or args.geo:
            raise ValueError(
                "--offline reuses the active map; omit --lat, --lon, --radius and --geo."
            )
    elif not args.skip_provision:
        if args.lat is None or args.lon is None:
            raise ValueError("--lat and --lon are required unless --skip-provision is used.")
        if args.radius is None:
            args.radius = DEFAULT_CENTER_RADIUS_METERS
        _select_and_provision_road(args, settings)
    state = load_active_map_state(paths=settings.paths)
    if args.carla_exe is not None:
        settings = replace(
            settings,
            carla=replace(settings.carla, executable_path=args.carla_exe),
        )
    return _run_uc01(
        settings=settings,
        state=state,
        once=args.once,
        check_calibration=args.check_calibration,
        visual_calibration=args.verify_calibration,
        offline=args.offline,
    )


def _build_traffic_provider(
    *,
    settings: AppSettings,
    profile: MapProfile,
    road_filter: str,
    offline: bool,
) -> TrafficDataProvider:
    if offline:
        from motion.infrastructure.offline import build_offline_provider

        LOGGER.info(
            "Offline mode enabled: HERE and Overpass acquisition are disabled; "
            "synthetic traffic will use the HERE v7 payload and parser contract."
        )
        return build_offline_provider(profile, profile.device_registry)

    from motion.infrastructure.here.factory import build_here_provider

    return build_here_provider(settings, profile, road_filter=road_filter)


def _run_uc01(
    *,
    settings: AppSettings,
    state: ActiveMapState,
    once: bool,
    check_calibration: bool,
    visual_calibration: bool,
    offline: bool,
) -> int:
    """Compose concrete adapters and invoke the UC-01 application service."""

    from motion.application.use_cases.uc01_real_time_traffic_mirroring.coverage import (
        MapCoverage,
    )
    from motion.application.use_cases.uc01_real_time_traffic_mirroring.filtering import (
        SegmentFilter,
    )
    from motion.application.use_cases.uc01_real_time_traffic_mirroring.reporting import (
        ConsoleDashboardReporter,
    )
    from motion.application.use_cases.uc01_real_time_traffic_mirroring.service import (
        TrafficMirrorService,
        exception_type_chain,
    )
    from motion.domain.devices import SyntheticDeviceProvider, synthesize_registry
    from motion.domain.mirroring import SpeedMirrorPolicy
    from motion.infrastructure.carla.adapter import CarlaTrafficSimulator
    from motion.infrastructure.carla.calibration import check_loaded_world
    from motion.infrastructure.maps.projection import build_geo_transform

    profile = state.to_profile(settings.paths)
    registry = profile.device_registry or synthesize_registry(profile)
    profile = replace(profile, device_registry=registry)
    projector = build_geo_transform(profile.osm_path, profile.proj_string)
    provider = _build_traffic_provider(
        settings=settings,
        profile=profile,
        road_filter=state.road_filter,
        offline=offline,
    )
    simulator = CarlaTrafficSimulator.from_profile(settings.carla, profile)
    service = TrafficMirrorService(
        traffic_provider=provider,
        device_provider=SyntheticDeviceProvider(registry),
        simulator=simulator,
        coverage=MapCoverage(profile, projector),
        speed_policy=SpeedMirrorPolicy(profile.speed_limit_kmh),
        segment_filter=SegmentFilter(
            road_filter=state.road_filter or settings.mirror.road_filter,
            geo_filter=state.geo_filter or settings.mirror.geo_filter,
            anchor_functional_class=(
                state.anchor_functional_class
                if state.anchor_functional_class is not None
                else settings.mirror.anchor_functional_class
            ),
        ),
        reporter=ConsoleDashboardReporter(
            profile.name,
            device_registry=profile.device_registry,
            traffic_source_label="SYNTHETIC HERE-COMPATIBLE" if offline else "HERE",
        ),
        update_interval_seconds=settings.mirror.update_interval_seconds,
    )
    try:
        if check_calibration or visual_calibration:
            try:
                calibration_segments = provider.fetch_segments()
            except Exception as error:
                LOGGER.warning(
                    "HERE calibration acquisition failed; continuing with "
                    "device anchors only (provider=%s, cause=%s)",
                    type(provider).__name__,
                    exception_type_chain(error),
                )
                calibration_segments = []
            calibration = check_loaded_world(
                world=simulator.world,
                carla_module=simulator.carla_module,
                profile=profile,
                projector=projector,
                segments=calibration_segments,
                visual=visual_calibration,
            )
            if not calibration.passed:
                return 1
        if once:
            service.prepare()
            service.run_tick()
            return 0
        service.run_forever()
        return 0
    finally:
        service.close()


def _handle_dataset_build(args: argparse.Namespace, _settings: AppSettings) -> int:
    from motion.prediction.dataset import build_dataset_files

    result = build_dataset_files(
        args.inputs,
        args.output,
        weather_rain_default=args.weather_rain_default,
    )
    print(f"Wrote {result.row_count} rows to {result.output_path}")
    return 0


def _handle_model_train(args: argparse.Namespace, settings: AppSettings) -> int:
    from motion.prediction.training import train_model_file

    output = args.output or settings.paths.models / "traffic_aimodel.pkl"
    result = train_model_file(args.dataset, output)
    print(f"Model: {result.model_path}")
    print(f"Accuracy: {result.metrics.accuracy:.3f}")
    return 0


def _handle_model_infer(args: argparse.Namespace, settings: AppSettings) -> int:
    from motion.infrastructure.carla.behavior_monitor import run_behavior_monitor

    model = args.model or settings.paths.models / "traffic_aimodel.pkl"
    if args.model is None and not model.is_file():
        reference_model = (
            settings.paths.root / "artifacts" / "reference" / "models" / "traffic_aimodel.pkl"
        )
        if reference_model.is_file():
            model = reference_model
    stats = args.stats_output or settings.paths.outputs / "realtime_inference_results.txt"
    return run_behavior_monitor(settings=settings, model_path=model, stats_path=stats)


def _handle_telemetry_collect(args: argparse.Namespace, settings: AppSettings) -> int:
    from motion.infrastructure.carla.telemetry import collect_telemetry

    output = args.output or settings.paths.telemetry
    path = collect_telemetry(
        settings=settings,
        output=output,
        duration_seconds=args.duration,
        sampling_interval_seconds=args.interval,
    )
    print(path)
    return 0


def _handle_speed_units(_args: argparse.Namespace, settings: AppSettings) -> int:
    from motion.infrastructure.carla.diagnostics import run_speed_unit_diagnostic

    return run_speed_unit_diagnostic(settings)


def _handle_calibration(args: argparse.Namespace, settings: AppSettings) -> int:
    from motion.infrastructure.carla.calibration import run_calibration

    state = load_active_map_state(paths=settings.paths)
    return run_calibration(settings=settings, state=state, visual=args.visual)


if __name__ == "__main__":
    raise SystemExit(main())
