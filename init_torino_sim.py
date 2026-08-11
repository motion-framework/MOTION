import carla
import xml.etree.ElementTree as ET
import random
import time

def main():
    client = carla.Client('localhost', 2000)
    client.set_timeout(30.0)
    
    with open("torino_map.xodr", 'r', encoding='utf-8') as f:
        xodr_content = f.read()
    params = carla.OpendriveGenerationParameters(0.5, 10.0, 0.1, 0.0, True, True, False)
    world = client.generate_opendrive_world(xodr_content, params)
    carla_map = world.get_map()
    
    spawn_points = carla_map.get_spawn_points()
    if spawn_points:
        world.get_spectator().set_transform(carla.Transform(
            spawn_points[0].location + carla.Location(z=80), 
            carla.Rotation(pitch=-90)))

    tm = client.get_trafficmanager(8000)
    tm.set_global_distance_to_leading_vehicle(2.5)

    blueprints = world.get_blueprint_library().filter('vehicle.*')
    vehicles_list = []

    print("Spawneando tráfico...")
    random.shuffle(spawn_points)
    for i in range(min(50, len(spawn_points))):
        v = world.try_spawn_actor(random.choice(blueprints), spawn_points[i])
        if v:
            v.set_autopilot(True, tm.get_port())
            p = v.get_physics_control()
            p.center_of_mass = carla.Vector3D(0, 0, -2.0)
            p.mass = 4000
            v.apply_physics_control(p)
            tm.auto_lane_change(v, False)
            vehicles_list.append(v)

    sensors = []
    try:
        tree = ET.parse('Datasets/torino_traffic.xml')
        root = tree.getroot()
        ns = {'ns': 'https://simone.5t.torino.it/ns/traffic_data.xsd'}
        for fdt in root.findall('ns:FDT_data', ns):
            sf = fdt.find('ns:speedflow', ns)
            lat, lon = float(fdt.get('lat')), float(fdt.get('lng'))
            v_real = float(sf.get('speed'))
            target_loc = carla_map.transform_to_location(carla.GeoLocation(lat, lon, 0))
            wp = carla_map.get_waypoint(target_loc)
            if wp and wp.transform.location.distance(target_loc) < 30.0:
                sensors.append({'loc': wp.transform.location, 'speed': v_real})
                world.debug.draw_point(wp.transform.location + carla.Location(z=2), 0.2, carla.Color(0,255,0), 500)
    except: pass

    print(f"Init simulation with {len(vehicles_list)} vehicles.")

    try:
        while True:
            vehicles_list = [v for v in vehicles_list if v.is_alive]

            if len(vehicles_list) < 40:
                new_v = world.try_spawn_actor(random.choice(blueprints), random.choice(spawn_points))
                if new_v:
                    new_v.set_autopilot(True, tm.get_port())
                    vehicles_list.append(new_v)

            for v in vehicles_list:
                try:
                    v_loc = v.get_location()
                    
                    if v_loc.z < -2.0:
                        v.set_transform(random.choice(spawn_points))
                        continue

                    for s in sensors:
                        if v_loc.distance(s['loc']) < 15.0:
                            tm.set_desired_speed(v, max(s['speed'], 15.0))
                except:
                    continue
            
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("Cleaning...")
        client.apply_batch([carla.command.DestroyActor(x.id) for x in vehicles_list if x.is_alive])

if __name__ == '__main__':
    main()