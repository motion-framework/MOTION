import carla
import math
import numpy as np
import joblib
import pandas as pd
import init_main_map as map_tool
import random
import time
import os

from model_features import MODEL_FEATURES
from map_profile import get_active_profile


TARGET_VEHICLE_COUNT = 80
SPAWN_TICK_INTERVAL = 30
tick_counter = 0
STATS_FILE = "realtime_inference_results.txt"

stats = {
    "total_alerts": 0,
    "true_positives": 0,
    "false_positives": 0,
    "lead_times": [],
    "inference_times": [],
    "start_time": time.time()
}

active_alerts_tracking = {}

try:
    model = joblib.load('traffic_aimodel.pkl')
    print("AI Model loaded.")
except Exception as e:
    print(f"Error loading AI Model: {e}")
    exit()

def save_stats_to_file(stats_dict):
    duration = time.time() - stats_dict["start_time"]
    with open(STATS_FILE, "w") as f:
        f.write(f"--- Real-Time validation log for {get_active_profile().name.capitalize()} scenario ---\n")
        f.write(f"Timestamp: {time.ctime()}\n")
        f.write(f"Test duration: {duration/60:.2f} minutes\n")
        f.write("-" * 40 + "\n")
        f.write(f"Total AI alerts: {stats_dict['total_alerts']}\n")
        f.write(f"Confirmed incidents (TP): {stats_dict['true_positives']}\n")
        f.write(f"False alarms (FP): {stats_dict['false_positives']}\n")

        if len(stats_dict["lead_times"]) > 0:
            avg_lead_time = sum(stats_dict["lead_times"]) / len(stats_dict["lead_times"])
            f.write(f"Mean prediction lead time: {avg_lead_time:.2f} seconds\n")
        if len(stats_dict["inference_times"]) > 0:
            avg_latency = sum(stats_dict["inference_times"]) / len(stats_dict["inference_times"])
            f.write(f"Mean Inference Latency: {avg_latency:.2f} ms\n")
            margin = 500 - avg_latency
            f.write(f"Safety Margin for T=0.5s: {margin:.2f} ms\n")
        if stats_dict['total_alerts'] > 0:
            precision = (stats_dict['true_positives'] / stats_dict['total_alerts']) * 100
            f.write(f"Current real-time precision: {precision:.2f}%\n")
        f.write("-" * 40 + "\n")

def asses_risk(v, ai_model, weather_rain):
    try:
        vel = v.get_velocity()
        speed = 3.6 * math.sqrt(vel.x**2 + vel.y**2 + vel.z**2)
        control = v.get_control()
        input_df = pd.DataFrame(
            [[speed, control.throttle, control.brake, control.steer, weather_rain]],
            columns=MODEL_FEATURES,
        )
        start_inference = time.perf_counter()
        prediction = ai_model.predict(input_df)[0]
        end_inference = time.perf_counter()

        latency_ms = (end_inference - start_inference) * 1000
        stats["inference_times"].append(latency_ms)

        return prediction
    except Exception as exc:
        # Fail visible: degrade gracefully for one vehicle, but never hide
        # a systemic failure (e.g. feature mismatch) behind silent zeros.
        print(f"[asses_risk] Inference failed for vehicle {v.id}: {exc}")
        return 0


client = carla.Client('localhost', 2000)
client.set_timeout(10.0)

world    = client.get_world()
map_name = world.get_map().name

# If the target map is already loaded, attach to it.
# Do not call initialize_world as it would wipe the existing world.
if "opendrive" in map_name.lower() or get_active_profile().name.lower() in map_name.lower():
    print(f"Attached to existing world: {map_name}")
    standalone = False
else:
    print(f"Map '{map_name}' is not the active profile. Loading world in standalone mode.")
    world = map_tool.initialize_world(client)
    standalone = True

map_tool.center_camera(world)

# map_tool.set_bad_weather(world)
# map_tool.spawn_pedestrians(client, world, 30)

tm = client.get_trafficmanager(8000)
tm.set_global_distance_to_leading_vehicle(1.5)

bp_library = world.get_blueprint_library()
blueprints = bp_library.filter('vehicle.*')
spawn_points = world.get_map().get_spawn_points()
random.shuffle(spawn_points)

debug = world.debug
risk_detected_vehicles = set()

print(f"\nStarting monitoring. Target: {TARGET_VEHICLE_COUNT} vehicles.")

try:
    while True:
        world.wait_for_tick()
        tick_counter += 1
        current_time = time.time()
        current_vehicles = world.get_actors().filter('vehicle.*')
        active_list = [v for v in current_vehicles if v.is_alive]

        # Weather is read once per tick, not once per vehicle (performance),
        # mirroring the same optimization in init_main_map_registration.py.
        weather_rain = round(world.get_weather().precipitation, 1)

        # Only spawn vehicles in standalone mode.
        # When traffic_mirror.py is running it manages the population.
        if standalone and len(active_list) < TARGET_VEHICLE_COUNT and tick_counter >= SPAWN_TICK_INTERVAL:
            tick_counter = 0
            bp = random.choice(blueprints)
            sp = random.choice(spawn_points)
            vehicle = world.try_spawn_actor(bp, sp)
            if vehicle:
                vehicle.set_autopilot(True, 8000)
                tm.vehicle_percentage_speed_difference(vehicle, 30.0)
                p = vehicle.get_physics_control()
                p.center_of_mass = carla.Vector3D(0, 0, -2.0)
                vehicle.apply_physics_control(p)

        for v in active_list:
            v_id = v.id
            try:
                risk = asses_risk(v, model, weather_rain)
                nearby_vehicles = [x for x in active_list if x.id != v.id and
                       x.get_location().distance(v.get_location()) < 15.0]
                if risk == 1 and len(nearby_vehicles) > 0:
                    loc = v.get_transform().location
                    debug.draw_arrow(loc + carla.Location(z=5), loc + carla.Location(z=2),
                                     thickness=0.2, arrow_size=0.3,
                                     color=carla.Color(255, 0, 0), life_time=0.1)
                    if v_id not in risk_detected_vehicles:
                        risk_detected_vehicles.add(v_id)
                        stats["total_alerts"] += 1
                        active_alerts_tracking[v_id] = {"start_time": current_time, "verified": False}
                        print(f"AI ALERT: Incident risk in vehicle {v_id} | Total alerts: {stats['total_alerts']}")
                        save_stats_to_file(stats)

                if v_id in active_alerts_tracking and not active_alerts_tracking[v_id]["verified"]:
                    control = v.get_control()
                    vel_val = 3.6 * math.sqrt(v.get_velocity().x**2 + v.get_velocity().y**2)

                    if control.brake > 0.8 and vel_val < 2.0:
                        l_time = current_time - active_alerts_tracking[v_id]["start_time"]
                        stats["true_positives"] += 1
                        stats["lead_times"].append(l_time)
                        active_alerts_tracking[v_id]["verified"] = True
                        print(f"---Incident validated for vehicle {v_id}")
                        save_stats_to_file(stats)

                if v_id in active_alerts_tracking:
                    elapsed = current_time - active_alerts_tracking[v_id]["start_time"]
                    if elapsed > 8.0:
                        if not active_alerts_tracking[v_id]["verified"]:
                            stats["false_positives"] += 1
                            print(f"---Expired alert for vehicle {v_id}")
                            save_stats_to_file(stats)

                        del active_alerts_tracking[v_id]
                        risk_detected_vehicles.discard(v_id)

            except Exception:
                continue

except KeyboardInterrupt:
    print("\nSimulation stopped by user.")
    save_stats_to_file(stats)
except Exception as e:
    print(f"\nError: {e}")
    save_stats_to_file(stats)
finally:
    print(f"Final results saved in: {STATS_FILE}")