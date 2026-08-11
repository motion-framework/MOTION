import carla
import time
import math


COMMANDED_VALUE = 30.0
WATCH_SECONDS = 20
LOOK_SECONDS_AFTER = 25


def measured_speed_kmh(vehicle):
    v = vehicle.get_velocity()
    return math.sqrt(v.x**2 + v.y**2 + v.z**2) * 3.6


print("Connecting to CARLA...")
client = carla.Client("localhost", 2000)
client.set_timeout(60.0)

world = client.get_world()
print("Using the currently loaded map.")

traffic_manager = client.get_trafficmanager(8000)

carla_map = world.get_map()
spawn_points = carla_map.get_spawn_points()
best_point, best_len = spawn_points[0], 0.0
for sp in spawn_points:
    wp = carla_map.get_waypoint(sp.location)
    if wp is None:
        continue
    length, current = 0.0, wp
    for _ in range(60):
        nxt = current.next(5.0)
        if not nxt:
            break
        if abs(nxt[0].transform.rotation.yaw - current.transform.rotation.yaw) > 10:
            break
        length += 5.0
        current = nxt[0]
    if length > best_len:
        best_len, best_point = length, sp
print(f"Spawn point has ~{best_len:.0f} m straight ahead.")

blueprint = world.get_blueprint_library().filter("vehicle.tesla.model3")[0]
vehicle = world.spawn_actor(blueprint, best_point)
vehicle.set_autopilot(True, 8000)
traffic_manager.set_desired_speed(vehicle, COMMANDED_VALUE)

spectator = world.get_spectator()
camera_location = carla.Location(
    x=best_point.location.x,
    y=best_point.location.y,
    z=best_point.location.z + 40.0,
)
camera_rotation = carla.Rotation(pitch=-70.0, yaw=best_point.rotation.yaw)
spectator.set_transform(carla.Transform(camera_location, camera_rotation))

print(f"\nCar spawned. Commanded {COMMANDED_VALUE} km/h.")
print("LOOK AT YOUR CARLA WINDOW, steady overhead view.\n")

peak = 0.0
for second in range(WATCH_SECONDS):
    time.sleep(1.0)
    speed_kmh = measured_speed_kmh(vehicle)
    peak = max(peak, speed_kmh)
    print(f"  {second+1:2d}s: {speed_kmh:5.1f} km/h")

print("\n" + "=" * 50)
print(f"  Commanded: {COMMANDED_VALUE}   |   Peak reached: {peak:.1f} km/h")
print("=" * 50)
if abs(peak - COMMANDED_VALUE) < 10:
    print("  VERDICT: KM/H ")
elif abs(peak - COMMANDED_VALUE * 3.6) < 30:
    print("  VERDICT: M/S -- divide by 3.6 in your code.")
else:
    print(f"  UNCLEAR -- peak {peak:.1f}. Paste the per-second list.")
print("=" * 50)

print(f"\nThe car will stay on screen for {LOOK_SECONDS_AFTER} more seconds -- look now.")
for remaining in range(LOOK_SECONDS_AFTER, 0, -1):
    print(f"  cleaning up in {remaining:2d}s...", end="\r")
    time.sleep(1.0)

vehicle.destroy()
print("\nCar removed. Done.")