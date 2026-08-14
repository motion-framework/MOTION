"""CARLA process, client and OpenDRIVE-world lifecycle."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from motion.config.settings import CarlaSettings

from .api import load_carla_module

SERVER_STARTUP_TIMEOUT_SECONDS = 180.0
SERVER_POLL_INTERVAL_SECONDS = 3.0
LOW_SPEC_ARGUMENTS = (
    "-quality-level=Low",
    "-windowed",
    "-ResX=800",
    "-ResY=600",
    "-dx11",
    "-benchmark",
    "-fps=30",
)


@dataclass(frozen=True, slots=True)
class OpenDriveGenerationSettings:
    vertex_distance_m: float = 2.0
    max_road_length_m: float = 50.0
    wall_height_m: float = 0.0
    additional_width_m: float = 0.6
    smooth_junctions: bool = True
    enable_mesh_visibility: bool = True


class CarlaLifecycle:
    """Own resources explicitly created for one CARLA session."""

    def __init__(
        self,
        settings: CarlaSettings,
        *,
        carla_loader: Callable[[], ModuleType] = load_carla_module,
        popen_factory: Callable[..., Any] = subprocess.Popen,
        monotonic_clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self._carla_loader = carla_loader
        self._popen_factory = popen_factory
        self._monotonic_clock = monotonic_clock
        self._sleep = sleep
        self._carla: ModuleType | None = None
        self._client: Any | None = None
        self._server_process: Any | None = None
        self._closed = False

    @property
    def carla(self) -> ModuleType:
        if self._carla is None:
            self._carla = self._carla_loader()
        return self._carla

    def connect(self) -> Any:
        if self._closed:
            raise RuntimeError("CARLA lifecycle is closed")
        if self._client is None:
            client = self.carla.Client(self.settings.host, self.settings.rpc_port)
            # The former final mirror path used 15 s.  UC-01 now consistently
            # honors centralized configuration (120 s by default).
            client.set_timeout(self.settings.client_timeout_seconds)
            self._client = client
        return self._client

    def server_version(self) -> str | None:
        try:
            return str(self.connect().get_server_version())
        except RuntimeError:
            self._client = None
            return None

    def start_server_if_configured(self) -> bool:
        executable = self.settings.executable_path
        if executable is None or self.server_version() is not None:
            return False
        if not executable.is_file():
            raise FileNotFoundError(f"CARLA executable not found: {executable}")
        self._server_process = self._popen_factory(
            [str(executable), *LOW_SPEC_ARGUMENTS],
            cwd=str(executable.parent),
        )
        self._client = None
        return True

    def wait_until_ready(self, timeout_seconds: float = SERVER_STARTUP_TIMEOUT_SECONDS) -> str:
        deadline = self._monotonic_clock() + timeout_seconds
        while self._monotonic_clock() < deadline:
            if self._server_process is not None:
                return_code = self._server_process.poll()
                if return_code is not None:
                    raise RuntimeError(
                        f"CARLA process exited during startup with code {return_code}"
                    )
            version = self.server_version()
            if version is not None:
                return version
            remaining = deadline - self._monotonic_clock()
            self._sleep(min(SERVER_POLL_INTERVAL_SECONDS, max(0.0, remaining)))
        raise TimeoutError(f"CARLA did not answer within {timeout_seconds:.0f} seconds")

    def load_open_drive_world(
        self,
        xodr_path: Path,
        generation: OpenDriveGenerationSettings | None = None,
    ) -> Any:
        parameters = generation or OpenDriveGenerationSettings()
        xodr_xml = xodr_path.read_text(encoding="utf-8")
        carla_parameters = self.carla.OpendriveGenerationParameters(
            vertex_distance=parameters.vertex_distance_m,
            max_road_length=parameters.max_road_length_m,
            wall_height=parameters.wall_height_m,
            additional_width=parameters.additional_width_m,
            smooth_junctions=parameters.smooth_junctions,
            enable_mesh_visibility=parameters.enable_mesh_visibility,
        )
        return self.connect().generate_opendrive_world(xodr_xml, carla_parameters)

    def traffic_manager(self) -> Any:
        manager = self.connect().get_trafficmanager(self.settings.traffic_manager_port)
        manager.set_global_distance_to_leading_vehicle(3.0)
        if hasattr(manager, "set_respawn_dormant_vehicles"):
            manager.set_respawn_dormant_vehicles(True)
        if hasattr(manager, "set_boundaries_respawn_dormant_vehicles"):
            manager.set_boundaries_respawn_dormant_vehicles(25, 700)
        return manager

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        process = self._server_process
        self._server_process = None
        self._client = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5.0)

    def __enter__(self) -> CarlaLifecycle:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.close()
