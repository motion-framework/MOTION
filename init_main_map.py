import carla
import time
import random
import traceback

from map_profile import get_active_profile


profile = get_active_profile()

XODR_PATH = profile.xodr_path
NUM_VEHICLES_DEFAULT = 45


def set_bad_weather(world):
    weather = carla.WeatherParameters(
        cloudiness=90.0,
        precipitation=90.0,
        precipitation_deposits=80.0,
        wind_intensity=70.0,
        sun_altitude_angle=10.0,
        fog_density=30.0,
        wetness=100.0
    )
    world.set_weather(weather)
    print("Weather set to: CRITICAL STORM")


def spawn_pedestrians(client, world, count):
    blueprint_library = world.get_blueprint_library()
    pedestrians_bp = blueprint_library.filter('walker.pedestrian.*')
    walker_controller_bp = blueprint_library.find('controller.ai.walker')

    walkers_list = []
    all_actors_ids = []

    spawn_points = []
    for i in range(count):
        loc = world.get_random_location_from_navigation()
        if loc is not None:
            spawn_points.append(carla.Transform(loc + carla.Location(z=0.5)))
        else:
            vehicle_points = world.get_map().get_spawn_points()
            if vehicle_points:
                ref_point = random.choice(vehicle_points)
                side_offset = carla.Location(x=random.uniform(3, 5), y=random.uniform(3, 5), z=0.5)
                spawn_points.append(carla.Transform(ref_point.location + side_offset))
    batch = []
    for i in range(len(spawn_points)):
        walker_bp = random.choice(pedestrians_bp)
        batch.append(carla.command.SpawnActor(walker_bp, spawn_points[i]))

    results = client.apply_batch_sync(batch, True)

    spawned_walkers = []
    for i in range(len(results)):
        if not results[i].error:
            spawned_walkers.append(world.get_actor(results[i].actor_id))
            all_actors_ids.append(results[i].actor_id)

    batch = []
    for walker in spawned_walkers:
        batch.append(carla.command.SpawnActor(walker_controller_bp, carla.Transform(), walker))

    results = client.apply_batch_sync(batch, True)

    world.wait_for_tick()
    for i in range(len(results)):
        if not results[i].error:
            controller_id = results[i].actor_id
            all_actors_ids.append(controller_id)

            controller = world.get_actor(controller_id)
            controller.start()
            random_vector = carla.Location(x=random.uniform(-10, 10), y=random.uniform(-10, 10))
            target_pos = spawn_points[i].location + random_vector
            controller.go_to_location(target_pos)
            controller.set_max_speed(float(random.uniform(1.2, 2.0)))

    print(f"Successfully spawned {len(spawned_walkers)} pedestrians.")
    return all_actors_ids


def setup_environment(world):
    print("Setting up safety ground...")
    bp_lib = world.get_blueprint_library()
    ground_bp = bp_lib.filter('static.prop.platform*')[0]
    spawn_points = world.get_map().get_spawn_points()

    for i in range(0, len(spawn_points), 100):
        p = spawn_points[i]
        t = carla.Transform(p.location + carla.Location(z=-0.5), p.rotation)
        ground = world.try_spawn_actor(ground_bp, t)
        if ground:
            ground.set_simulate_physics(False)
    print("Environment Ready.")


def center_camera(world):
    spectator = world.get_spectator()
    spawn_points = world.get_map().get_spawn_points()
    if spawn_points:
        center_x = sum(p.location.x for p in spawn_points) / len(spawn_points)
        center_y = sum(p.location.y for p in spawn_points) / len(spawn_points)
        center_location = carla.Location(x=center_x, y=center_y, z=100.0)
        center_rotation = carla.Rotation(pitch=-90, yaw=0, roll=0)
        spectator.set_transform(carla.Transform(center_location, center_rotation))
        print(f"Camera centered at: {center_x:.2f}, {center_y:.2f}")


def initialize_world(client):
    print(f"Loading {profile.name.capitalize()}...")
    with open(XODR_PATH, 'r', encoding='utf-8') as f:
        xodr_xml = f.read()

    world = client.generate_opendrive_world(xodr_xml, carla.OpendriveGenerationParameters(
        vertex_distance=2.0, max_road_length=50.0, wall_height=0.0,
        additional_width=0.6, smooth_junctions=True, enable_mesh_visibility=True))

    time.sleep(2.0)
    setup_environment(world)

    # ADDED
    print(f"[initialize_world] Active map after generation: {world.get_map().name}")
    
    return world

# CHANGED: Added get_traffic_manager
def get_traffic_manager(client, port: int = 8000):
    tm = client.get_trafficmanager(port)
    tm.set_global_distance_to_leading_vehicle(3.0)
    tm.set_respawn_dormant_vehicles(True)
    tm.set_boundaries_respawn_dormant_vehicles(25, 700)
    return tm


if __name__ == "__main__":
    try:
        client = carla.Client('localhost', 2000)
        client.set_timeout(60.0)
        world = initialize_world(client)
        center_camera(world)

        blueprints = world.get_blueprint_library().filter('vehicle.*')
        spawn_points = world.get_map().get_spawn_points()
        random.shuffle(spawn_points)

        for i in range(min(NUM_VEHICLES_DEFAULT, len(spawn_points))):
            v = world.try_spawn_actor(random.choice(blueprints), spawn_points[i])
            if v: v.set_autopilot(True)

        # CHANGED: Here Traffic Integration
        from here_traffic import TrafficService

        traffic_service = TrafficService(client,world)
        traffic_service.update()

        print("Running standalone. Press Ctrl+C to stop.")

        while True:
            world.wait_for_tick()

    except Exception:
        traceback.print_exc()