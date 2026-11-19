"""Shared live/offline traffic-provider selection.

Extracted from the ``motion mirror`` composition so ``motion scenario
simulate`` and ``motion infra-event simulate`` select between live HERE
acquisition and the offline synthetic HERE-compatible provider identically.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from motion.config.settings import AppSettings
    from motion.domain.maps import MapProfile
    from motion.ports.traffic import TrafficDataProvider

LOGGER = logging.getLogger(__name__)


def build_traffic_provider(
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
