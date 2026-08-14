"""Offline checks for the MOTION macro use-case catalog."""

from __future__ import annotations

import importlib
import unittest

from motion.application.use_cases.catalog import USE_CASE_CATALOG
from motion.application.use_cases.descriptor import UseCaseStatus

DEDICATED_PACKAGES = (
    (
        "motion.application.use_cases.uc01_real_time_traffic_mirroring",
        "UC-01",
    ),
    ("motion.application.use_cases.uc02_what_if_scenario", "UC-02"),
    (
        "motion.application.use_cases.uc03_infrastructure_event_simulation",
        "UC-03",
    ),
    (
        "motion.application.use_cases.uc04_multivariate_traffic_prediction",
        "UC-04",
    ),
    (
        "motion.application.use_cases.uc05_environmental_impact_forecast",
        "UC-05",
    ),
    (
        "motion.application.use_cases.uc06_luminosity_anomaly_detection",
        "UC-06",
    ),
    ("motion.application.use_cases.uc07_governance_alerts", "UC-07"),
)


class UseCaseCatalogTest(unittest.TestCase):
    def test_catalog_contains_seven_unique_ordered_ids(self) -> None:
        use_case_ids = [descriptor.use_case_id for descriptor in USE_CASE_CATALOG]

        self.assertEqual(
            use_case_ids,
            [f"UC-{number:02d}" for number in range(1, 8)],
        )
        self.assertEqual(len(use_case_ids), len(set(use_case_ids)))

    def test_each_use_case_has_a_dedicated_importable_package(self) -> None:
        descriptors_by_id = {descriptor.use_case_id: descriptor for descriptor in USE_CASE_CATALOG}

        for module_name, use_case_id in DEDICATED_PACKAGES:
            with self.subTest(module_name=module_name):
                module = importlib.import_module(module_name)
                self.assertIs(module.USE_CASE, descriptors_by_id[use_case_id])

    def test_statuses_do_not_advertise_research_directions_as_implemented(self) -> None:
        self.assertEqual(USE_CASE_CATALOG[0].status, UseCaseStatus.IMPLEMENTED)

        for descriptor in USE_CASE_CATALOG[1:]:
            with self.subTest(use_case_id=descriptor.use_case_id):
                self.assertEqual(
                    descriptor.status,
                    UseCaseStatus.NOT_IMPLEMENTED_RESEARCH_DIRECTION,
                )

    def test_every_descriptor_carries_traceability_and_gap_information(self) -> None:
        for descriptor in USE_CASE_CATALOG:
            with self.subTest(use_case_id=descriptor.use_case_id):
                self.assertTrue(descriptor.goal)
                self.assertTrue(descriptor.actor)
                self.assertTrue(descriptor.evidence)
                self.assertTrue(descriptor.dependencies)
                self.assertTrue(descriptor.missing_behavior)
                self.assertTrue(descriptor.document_references)


if __name__ == "__main__":
    unittest.main()
