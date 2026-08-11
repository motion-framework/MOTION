from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import carla

from dataclasses import dataclass
from dotenv import load_dotenv


MIRROR_ROAD_SCRIPT = "mirror_road.py"
CARLA_HOST = "localhost"
CARLA_RPC_PORT = 2000
SERVER_HANDSHAKE_TIMEOUT_SECONDS = 4.0
SERVER_STARTUP_TIMEOUT_SECONDS = 180.0
SERVER_POLL_INTERVAL_SECONDS = 3.0
MAP_LOAD_TIMEOUT_SECONDS = 120.0

CARLA_LOW_SPEC_ARGUMENTS = [
    "-quality-level=Low",
    "-windowed",
    "-ResX=800",
    "-ResY=600",
    "-dx11",
    "-benchmark",
    "-fps=30",
]

LOG_PREFIX = "[run_traffic_mirror]"


@dataclass(frozen=True)
class MirrorRunRequest:
    latitude: float | None
    longitude: float | None
    radius_meters: float | None
    select_nearest_road_by_geometry: bool
    map_name: str
    carla_executable_path: str
    skip_provisioning: bool
    run_calibration_check: bool
    run_visual_verification: bool


class TrafficMirrorLauncher:
    def __init__(self, request: MirrorRunRequest) -> None:
        self._request = request
        self._carla_server_process: subprocess.Popen | None = None

    # Step 1
    def provision_map_from_here_coverage(self) -> None:
        if self._request.skip_provisioning:
            print(f"{LOG_PREFIX} Skipping provisioning; reusing the map already in .env. ")
            return

        command = [
            sys.executable,
            MIRROR_ROAD_SCRIPT,
            "--lat", f"{self._request.latitude:.6f}",
            "--lon", f"{self._request.longitude:.6f}",
            "--name", self._request.map_name,
        ]

        if self._request.radius_meters is not None:
            command += ["--radius", str(self._request.radius_meters)]
        if self._request.select_nearest_road_by_geometry:
            command.append("--geo")

        print(f"{LOG_PREFIX} Step 1/5: provisioning the map from HERE coverage.")
        print(f"{LOG_PREFIX} Running: {' '.join(command)}")
        result = subprocess.run(command)
        if result.returncode != 0:
            raise SystemExit(
                f"{MIRROR_ROAD_SCRIPT} failed with exit code {result.returncode}. "
                "See its output above. Nothing was started in CARLA."
            )

        load_dotenv(override=True)

        print(f"{LOG_PREFIX} Map provisioned. Active map is now '{os.environ.get('ACTIVE_MAP_NAME')}'. ")

    # Step 2
    def start_carla_server_if_requested(self) -> None:
        if not self._request.carla_executable_path:
            print(f"{LOG_PREFIX} Step 2/5: no CARLA path set (--carla-exe or .env). Expecting CARLA to be running already. ")
            return

        if self._probe_server_version() is not None:
            print(f"{LOG_PREFIX} Step 2/5: a CARLA server is already answering on "
                  f"{CARLA_HOST}:{CARLA_RPC_PORT}; reusing it instead of starting another.")
            return

        if not os.path.exists(self._request.carla_executable_path):
            raise SystemExit(
                f"CARLA executable not found: {self._request.carla_executable_path}"
            )

        command = [self._request.carla_executable_path] + CARLA_LOW_SPEC_ARGUMENTS

        print(f"{LOG_PREFIX} Step 2/5: starting CARLA server.")
        print(f"{LOG_PREFIX} Running: {' '.join(command)}")
        self._carla_server_process = subprocess.Popen(
            command,
            cwd=os.path.dirname(self._request.carla_executable_path) or None,
        )

    # Step 3
    def wait_until_carla_server_answers(self) -> None:
        print(f"{LOG_PREFIX} Step 3/5: waiting for the CARLA server on {CARLA_HOST}:{CARLA_RPC_PORT}.")
        deadline = time.time() + SERVER_STARTUP_TIMEOUT_SECONDS

        while time.time() < deadline:
            server_version = self._probe_server_version()
            if server_version is not None:
                print(f"{LOG_PREFIX} CARLA server is up. Version: {server_version}")
                return
            seconds_left = deadline - time.time()
            print(f"{LOG_PREFIX} Server not answering yet. Retrying ({seconds_left:.0f} s left).")
            time.sleep(SERVER_POLL_INTERVAL_SECONDS)

        raise SystemExit(
            f"CARLA did not answer within {SERVER_STARTUP_TIMEOUT_SECONDS:.0f} s. "
            "Start it manually and re-run with --skip-provision. "
        )

    @staticmethod
    def _probe_server_version() -> str | None:
        try:
            probe_client = carla.Client(CARLA_HOST, CARLA_RPC_PORT)
            probe_client.set_timeout(SERVER_HANDSHAKE_TIMEOUT_SECONDS)
            return probe_client.get_server_version()
        except RuntimeError:
            return None

    # Step 4a
    def run_calibration_check(self) -> None:
        if not self._request.run_calibration_check:
            print(f"{LOG_PREFIX} Step 4/5: skipping calibration check (pass --check-calibration to run it). ")
            return

        print(f"{LOG_PREFIX} Step 4/5: loading the map so the calibration check has something to measure. ")
        import init_main_map
        import check_map_calibration

        client = carla.Client(CARLA_HOST, CARLA_RPC_PORT)
        client.set_timeout(MAP_LOAD_TIMEOUT_SECONDS)
        init_main_map.initialize_world(client)

        exit_code = check_map_calibration.main()
        if exit_code != 0:
            raise SystemExit(
                "Calibration check FAILED. Markers do not lie on the road network, "
                "so any traffic mirrored onto this map would be placed on the wrong geometry. "
                "Fix the calibration before collecting data. "
            )
        print(f"{LOG_PREFIX} Calibration check passed. ")

    # Step 4b
    def run_visual_verification_step(self) -> None:
        if not self._request.run_visual_verification:
            print(
                f"{LOG_PREFIX} Visual calibration: skipped "
                "(pass --verify-calibration to draw markers in the CARLA window)."
            )
            return

        print(
            f"{LOG_PREFIX} Visual calibration: loading the map and placing "
            "diagnostic markers in the CARLA window."
        )
        import init_main_map
        import verify_map_calibration

        client = carla.Client(CARLA_HOST, CARLA_RPC_PORT)
        client.set_timeout(MAP_LOAD_TIMEOUT_SECONDS)
        world = init_main_map.initialize_world(client)
        init_main_map.center_camera(world)
        verify_map_calibration.main()

        print(
            f"{LOG_PREFIX} Markers are live in the CARLA window for "
            f"{verify_map_calibration.MARKER_LIFETIME:.0f} seconds."
        )
        print(f"{LOG_PREFIX} Green = bbox corners.  Red = field devices.  Blue = HERE segments.")
        print(f"{LOG_PREFIX} Press Enter when you have finished checking the markers.")
        input()

    # Step 5
    def run_traffic_mirror(self) -> None:
        print(f"{LOG_PREFIX} Step 5/5: starting the traffic mirror. Press Ctrl+C to stop. ")
        import traffic_mirror
        traffic_mirror.run()

    # Orchestration
    def run(self) -> None:
        self.provision_map_from_here_coverage()
        self.start_carla_server_if_requested()
        self.wait_until_carla_server_answers()
        self.run_calibration_check()
        self.run_visual_verification_step()
        self.run_traffic_mirror()


def parse_arguments() -> MirrorRunRequest:
    parser = argparse.ArgumentParser(
        description="Run the whole live traffic mirror from one command. "
    )
    parser.add_argument("--lat", type=float, help="Latitude of the area to mirror")
    parser.add_argument("--lon", type=float, help="Longitude of the area to mirror")
    parser.add_argument(
        "--radius", type=float, default=None,
        help="Half-width of the mirrored area in metres. "
             "This is what decides  how much OF THE ROAD gets simulated: radius 400 mirrors roughly 800 m of it. "
             "Defaults to mirror_road.py's own default.",
    )
    parser.add_argument(
        "--geo", action="store_true",
        help="Skip the menu and mirror the road nearest --lat/--lon, "
             "chosen by true geometry (works for unnamed roads). Omit to choose from an interactive menu.",
    )
    parser.add_argument("--name", default="here_road", help="Identifier used for this map's files")
    parser.add_argument("--carla-exe", default="", help="Path to CarlaUE4.exe. If omitted, CARLA_EXECUTABLE_PATH from .env is used; "
             "if neither is set, CARLA is assumed to be already running. ",
    )
    parser.add_argument("--skip-provision", action="store_true", help="Reuse the map already recorded in .env")
    parser.add_argument("--check-calibration", action="store_true",
                        help="Run the automated calibration check first. Recommended once per new map.")
    parser.add_argument("--verify-calibration", action="store_true", help=
        "Draw visual calibration markers in the CARLA window after loading the map. "
        "Use this once per new map to visually confirm that devices and HERE segments land on the correct roads."
    )

    arguments = parser.parse_args()

    needs_coordinates = not arguments.skip_provision
    if needs_coordinates and (arguments.lat is None or arguments.lon is None):
        parser.error("--lat and --lon are required unless you pass --skip-provision.")

    load_dotenv()
    
    carla_executable_path = arguments.carla_exe or os.environ.get("CARLA_EXECUTABLE_PATH", "")

    return MirrorRunRequest(
        latitude=arguments.lat,
        longitude=arguments.lon,
        radius_meters=arguments.radius,
        select_nearest_road_by_geometry=arguments.geo,
        map_name=arguments.name,
        carla_executable_path=carla_executable_path,
        skip_provisioning=arguments.skip_provision,
        run_calibration_check=arguments.check_calibration,
        run_visual_verification=arguments.verify_calibration,
    )


if __name__ == "__main__":
    TrafficMirrorLauncher(parse_arguments()).run()