from __future__ import annotations

import unittest
from types import SimpleNamespace

from motion.infrastructure.carla.population import OwnedVehicleRegistry
from motion.infrastructure.carla.sanitizer import (
    FellThroughMapRule,
    FleetSanitizer,
    FrozenInTrafficRule,
)


class Actor:
    def __init__(self, actor_id, *, z=0.0, speed=0.0):
        self.id = actor_id
        self.is_alive = True
        self._location = SimpleNamespace(x=0.0, y=0.0, z=z)
        self._velocity = SimpleNamespace(x=speed, y=0.0, z=0.0)

    def get_location(self):
        return self._location

    def get_velocity(self):
        return self._velocity


class Population:
    def __init__(self, registry):
        self.registry = registry
        self.destroyed = []

    def destroy(self, actors):
        actors = [actor for actor in actors if self.registry.owns(actor)]
        for actor in actors:
            self.destroyed.append(actor.id)
            self.registry.forget(actor.id)
        return len(actors)


class SanitizerTest(unittest.TestCase):
    def test_fell_through_rule_scans_only_owned_registry(self):
        external = Actor(1, z=-2.0)
        owned = Actor(2, z=-2.0)
        registry = OwnedVehicleRegistry()
        registry.register(owned)
        population = Population(registry)
        sanitizer = FleetSanitizer(
            world=object(),
            population_manager=population,
            registry=registry,
            rules=(FellThroughMapRule(),),
        )

        removed = sanitizer.run(set())

        self.assertEqual(removed, 1)
        self.assertEqual(population.destroyed, [2])
        self.assertTrue(external.is_alive)

    def test_frozen_rule_preserves_strictly_greater_than_sixty_seconds(self):
        now = [100.0]
        actor = Actor(7, speed=0.0)
        rule = FrozenInTrafficRule(clock=lambda: now[0])

        self.assertFalse(rule.should_remove(actor))
        now[0] = 160.0
        self.assertFalse(rule.should_remove(actor))
        now[0] = 160.001
        self.assertTrue(rule.should_remove(actor))


if __name__ == "__main__":
    unittest.main()
