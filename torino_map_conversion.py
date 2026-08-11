import io
import carla

with open("torino_map.osm", 'r', encoding='utf-8') as f:
    osm_data = f.read()

settings = carla.Osm2OdrSettings()
settings.set_osm_way_types(["motorway", "motorway_link", "trunk", "primary", "secondary", "tertiary"])

xodr_data = carla.Osm2Odr.convert(osm_data, settings)

with open("torino_map.xodr", "w") as f:
    f.write(xodr_data)

vertex_distance = 2.0
max_road_length = 500.0
wall_height = 0.0
extra_width = 0.6

client = carla.Client('localhost', 2000)
client.set_timeout(60.0)
world = client.generate_opendrive_world(xodr_data, carla.OpendriveGenerationParameters(
    vertex_distance, max_road_length, wall_height, extra_width, True))
spawn_points = world.get_map().get_spawn_points()
if spawn_points:
    setup_loc = spawn_points[0].location
    spectator = world.get_spectator()
    spectator.set_transform(carla.Transform(setup_loc + carla.Location(z=50), carla.Rotation(pitch=-90)))
    print(f"Cámara movida a: {setup_loc}")