import carla
import time
import math
import pandas as pd
import os
import datetime

OUTPUT_DIR = ".\\DataCSV"
DURATION_SIM = 180  
SAMPLING_INTERVAL = 0.5 

collisions_registered = {}
collisioned_vehicles = set()

def collision_callback(event, dict_collisions):
    actor_id = event.actor.id
    if actor_id not in collisioned_vehicles:
        dict_collisions[actor_id] = True
        collisioned_vehicles.add(actor_id)
        print(f" >>> [COLISIÓN] ID: {actor_id}")

def main():
    client = carla.Client('localhost', 2000)
    client.set_timeout(60.0)
    
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(OUTPUT_DIR, f'dataset_collisions_{timestamp_str}.csv')

    vehicles_list = []
    sensors_list = []
    data_log = []

    try:
        world = client.get_world()
        print("----------------------------------------------------------")
        print("STATUS: Waiting for ScenarioRunner vehicles...")

        while True:
            existing_vehicles = world.get_actors().filter('vehicle.*')
            if len(existing_vehicles) > 0:
                vehicles_list = list(existing_vehicles)
                break
            time.sleep(0.5)
        
        print(f"STATUS: {len(vehicles_list)} detected vehicles. Connecting sensors...")

        collision_bp = world.get_blueprint_library().find('sensor.other.collision')
        for vehicle in vehicles_list:
            col_sensor = world.spawn_actor(collision_bp, carla.Transform(), attach_to=vehicle)
            col_sensor.listen(lambda event: collision_callback(event, collisions_registered))
            sensors_list.append(col_sensor)

        print(f"STATUS: Recording in {output_file}...")
        start_time = time.time()
        last_record_time = 0

        while True:
            elapsed_time = time.time() - start_time
            
            if elapsed_time > DURATION_SIM:
                print("INFO: Simulation recording time reached.")
                break

            active_vehicles = [v for v in vehicles_list if v.is_alive]
            if not active_vehicles:
                print("INFO: Vehicles not detected. Closing register...")
                break

            world.wait_for_tick()

            if elapsed_time - last_record_time >= SAMPLING_INTERVAL:
                for v in active_vehicles:
                    transform = v.get_transform()
                    loc = transform.location
                    vel = v.get_velocity()
                    speed_kmh = 3.6 * math.sqrt(vel.x**2 + vel.y**2 + vel.z**2)
                    control = v.get_control()
                    
                    data_log.append({
                        'timestamp': round(elapsed_time, 2),
                        'v_id': v.id,
                        'x': round(loc.x, 2),
                        'y': round(loc.y, 2),
                        'speed_kmh': round(speed_kmh, 2),
                        'throttle': round(control.throttle, 3), 
                        'brake': round(control.brake, 3),        
                        'steer': round(control.steer, 3),       
                        'collision': 1 if v.id in collisions_registered else 0
                    })
                last_record_time = elapsed_time

    except Exception as e:
        print(f"ERROR: {e}")
    
    finally:
        if data_log:
            print("----------------------------------------------------------")
            print("STATUS: Saving data in CSV...")
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            df = pd.DataFrame(data_log)
            df.to_csv(output_file, index=False)
            print(f"SUCESS: File saved and closed: {output_file}")
        else:
            print("WARNING: No data was generated to save.")

        print("STATUS: Cleaning sensors...")
        for s in sensors_list:
            if s.is_alive:
                s.destroy()
        print("DONE.")

if __name__ == "__main__":
    main()