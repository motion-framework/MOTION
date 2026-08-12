# Traffic Modelling
# Using CARLA Simulator and OpenStreetMap

A thesis project that mirrors real-world traffic from the HERE Traffic API
into the CARLA driving simulator, records vehicle telemetry.

---

## Table of Contents

1. [What This Project Does](#what-this-project-does)
2. [What You Need Before Starting](#what-you-need-before-starting)
3. [Step 1: Install CARLA Simulator](#step-1-install-carla-simulator)
4. [Step 2: Install Python](#step-2-install-python)
5. [Step 3: Clone This Repository](#step-3-clone-this-repository)
6. [Step 4: Install Python Dependencies](#step-4-install-python-dependencies)
7. [Step 5: Get a HERE API Key](#step-5-get-a-here-api-key)
8. [Step 6: Configure the Environment File](#step-6-configure-the-environment-file)
9. [Running the Project](#running-the-project)
10. [All Available Commands](#all-available-commands)
11. [Manual OSM Download (When Overpass Is Down)](#manual-osm-download-when-overpass-is-down)
12. [The Machine Learning Pipeline](#the-machine-learning-pipeline)
13. [Troubleshooting](#troubleshooting)
14. [Project Structure](#project-structure)
15. [How It Works (Technical Summary)](#how-it-works-technical-summary)
16. [References](#references)

---

## What This Project Does

This project picks a real road anywhere in the world, 
downloads its map from OpenStreetMap, loads it into the CARLA driving simulator, 
and then makes the simulated traffic behave like the real traffic on that road right now. 
It does this by reading live speed and congestion data 
from the HERE Traffic API every 60 seconds and adjusting the simulated vehicles to match.

---

## What You Need Before Starting

Before you install anything, make sure you have:

- **A computer running Windows 10 or 11** (this project was developed
  and tested on Windows).
- **A dedicated GPU with at least 4 GB of video memory.** 
  CARLA is a 3D simulator and will not run without a GPU. 
  NVIDIA GTX 1650 Super or better is recommended. 
  AMD GPUs may work but are not tested.
- **At least 30 GB of free disk space.** CARLA alone is about 20 GB.
- **An internet connection** for downloading dependencies, map data, and
  live traffic data from HERE.

---

## Step 1: Install CARLA Simulator

CARLA is the driving simulator this project uses. 
You need version **0.9.16** specifically. 
Other versions may not be compatible.

1. Open your web browser.
2. Go to: https://github.com/carla-simulator/carla/releases/tag/0.9.16/
3. Scroll down to the **Assets** section.
4. Download `CARLA_0.9.16.zip` (about 20 GB).
5. Once downloaded, right-click the zip file and click **Extract All**.
6. Choose a location you will remember. For example: `C:\CARLA_0.9.16`
7. After extraction, open the folder. 
   You should see a file called `CarlaUE4.exe`. 
   Remember the full path to this file. 
   For example: `C:\CARLA_0.9.16\CarlaUE4.exe`

**Do not run CARLA yet.** 
The project will start it automatically, or
you can start it manually later.

### How to Start CARLA Manually (If Needed)

Open a terminal (press `Win + R`, type `cmd`, press Enter). 
Type:
cd C:\CARLA_0.9.16
CarlaUE4.exe -quality-level=Low

The `-quality-level=Low` flag reduces GPU memory usage. 
On a 4 GB GPU, this is strongly recommended. 
A window will open showing an empty 3D world. 
Leave it running and open a second terminal for the Python commands.

---

## Step 2: Install Python

This project requires **Python 3.12**.

1. Go to: https://www.python.org/downloads/
2. Download the latest Python 3.12 installer for Windows.
3. **IMPORTANT:** 
   When the installer opens, 
   check the box that says **"Add Python to PATH"** at the bottom of the first screen. 
   If you miss this, nothing will work from the terminal.
4. Click **Install Now** and wait for it to finish.

To verify it worked, open a terminal and type:
python --version

You should see something like `Python 3.12.0`. 
If you see an error like `'python' is not recognized`, 
Python was not added to PATH. 
Uninstall and reinstall with the PATH checkbox checked.

---

## Step 3: Clone This Repository

"Cloning" means downloading this project's code to your computer using Git.

### If You Do Not Have Git Installed

1. Go to: https://git-scm.com/download/win
2. Download and run the installer. Accept all default options.
3. Close and reopen your terminal.

### Clone the Project

Open a terminal. 
Navigate to where you want the project folder to be created. 
For example, to put it on your desktop:
cd %USERPROFILE%\Desktop

Then clone:
git clone https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git

Replace `YOUR_USERNAME/YOUR_REPO_NAME` with the actual repository URL.

Then enter the project folder:

cd YOUR_REPO_NAME

You are now inside the project directory. 
All commands from this point forward assume you are in this directory.

---

## Step 4: Install Python Dependencies

In the project root
`py -3.12 -m venv venv`
to use a virtual environment.

then
`cd venv` -> `cd Scripts` -> `activate.bat`

then cd to where the requirements.txt is located.

This project uses several Python libraries. 
Install them all at once:
pip install -r requirements.txt

This reads the `requirements.txt` file and installs everything listed.
It may take a few minutes.

### Install the CARLA Python API

The CARLA Python API is not on PyPI (the normal `pip` repository). 
You need to install it from the file that came with CARLA.

1. Open the CARLA folder you extracted in Step 1.
2. Look for a folder called `PythonAPI\carla\dist\`.
3. Inside, find a file that looks like:
   `carla-0.9.16-cp310-cp310-win_amd64.whl`
   (the `cp310` part must match your Python version: `cp310` for
   Python 3.10, `cp311` for 3.11, `cp312` for 3.12).
4. Verify the python version `python --version`
5. Install it:
pip install C:\CARLA_0.9.16\PythonAPI\carla\dist\carla-0.9.16-cp312-cp312-win_amd64.whl

Adjust the path and filename to match your setup.

---

## Step 5: Get a HERE API Key

HERE provides the live traffic data. 
You need a free API key.

1. Go to: https://platform.here.com/
2. Click **Sign Up** and create a free account.
3. After signing in, go to **Projects** (left sidebar).
4. Create a new project (use any name).
5. Inside the project, click **Create API Key**.
6. Copy the API key. It is a long string of letters and numbers.

The free tier allows 250,000 API calls per month. 
This project makes about 2 calls per minute (one for flow, one for incidents), 
so you can run it continuously for over 80 days before hitting the limit.

---

## Step 6: Configure the Environment File

The project reads configuration from a file called `.env` in the project root directory. Create it now.

1. In the project folder, create a new text file.
2. Rename it to `.env` (just a dot, then `env`, no other extension).
   Windows may warn you about changing the extension. 
   Click **Yes**.
3. Open it with Notepad or any text editor.
4. Paste the following and fill in your values:

HERE_API_KEY=paste_your_here_api_key_here
CARLA_EXECUTABLE_PATH=C:\CARLA_0.9.16\CarlaUE4.exe
HERE_ARCHIVE_MODE=off
OSM_DOWNLOADER_CONTACT_EMAIL=your_email@example.com

Replace `paste_your_here_api_key_here` with the key from Step 5.
Replace the CARLA path with wherever you extracted CARLA.
Replace the email with your real email 
(Overpass API etiquette asks for a contact email; it is never shared publicly).

5. Save the file.

**Do not share the `.env` file or commit it to Git.** 
It contains your private API key. 
The `.gitignore` file in this project already excludes it.

---

## Running the Project

### The One Command That Does Everything

python run_traffic_mirror.py --lat 40.6772 --lon 14.7604 --radius 400 --geo

This single command:

1. Queries HERE for roads near latitude 40.6772, longitude 14.7604.
2. Automatically picks the nearest road (`--geo` flag).
3. Downloads the OpenStreetMap data for a 400-metre radius around that road.
4. Converts the map to CARLA's OpenDRIVE format.
5. Scans and patches any geometry problems in the converted map.
6. Launches CARLA (if `CARLA_EXECUTABLE_PATH` is set in `.env`).
7. Loads the map into CARLA.s
8. Starts the traffic mirror: spawning vehicles and adjusting their
   speeds every 60 seconds to match HERE's live data.

The mirror runs until you press `Ctrl + C` to stop it.

### If CARLA Is Already Running

If you started CARLA manually (see Step 1), the script will connect to
the existing instance instead of launching a new one.

### Picking a Road Interactively

Remove the `--geo` flag to see a numbered menu of nearby roads:


python run_traffic_mirror.py --lat 40.6772 --lon 14.7604 --radius 400

The script will print a list of roads HERE monitors in that area. 
Type the number of the road you want and press Enter.

### Reusing an Existing Map

If you already ran the project once and want to restart without
re-downloading the map:

python run_traffic_mirror.py --skip-provision


### Running with Calibration Check

To verify that the coordinate transformation is correct before starting the mirror:

python run_traffic_mirror.py --lat 40.6772 --lon 14.7604 --radius 400 --geo --check-calibration

To see visual markers in the CARLA window:

python run_traffic_mirror.py --lat 40.6772 --lon 14.7604 --radius 400 --geo --verify-calibration


### Recording HERE Data for Thesis Evidence

Set `HERE_ARCHIVE_MODE=record` in your `.env` file before running.
Every HERE API response will be saved as timestamped, SHA-256-hashed JSON in the `DataHERE/` folder. 
This is the primary evidence that the traffic data that was discussed in the project is real.

---

## All Available Commands

### Full Pipeline

Command : `python run_traffic_mirror.py --lat LAT --lon LON --radius R --geo`
What It Does : Everything: pick road, build map, start mirror

Command : `python run_traffic_mirror.py --lat LAT --lon LON --radius R`
What It Does : Same but shows interactive road menu

Command : `python run_traffic_mirror.py --skip-provision`
What It Does : Reuse existing map, start mirror directly

Command : `python run_traffic_mirror.py --skip-provision --check-calibration`
What It Does : Automated calibration check, then mirror

Command : `python run_traffic_mirror.py --skip-provision --verify-calibration`
What It Does : Visual calibration markers, then mirror

### Individual Steps (Advanced)

`python mirror_road.py --lat LAT --lon LON --radius R --geo`
Pick a road and configure the map profile only

`python provision_map.py --lat LAT --lon LON --radius R --name NAME`
Download and convert map only

`python traffic_mirror.py`
Run the mirror only (map must be loaded in CARLA)


### Map Tools

`python find_degenerate_geometry.py maps\NAME\NAME_map.xodr`
Scan for zero-length geometries

`python patch_zero_length_geometry.py maps\NAME\NAME_map.xodr`
Fix zero-length geometries

`python find_crosswalk_overflow.py maps\NAME\NAME_map.xodr`
Scan for crosswalks past road end

`python patch_crosswalk_overflow.py maps\NAME\NAME_map.xodr`
Fix crosswalk overflows

`python inspect_osm_bounds.py maps\NAME\NAME.osm`
Print OSM file bounds and statistics

### Calibration

`python check_map_calibration.py`
Automated pass/fail check (needs CARLA running)

`python verify_map_calibration.py`
Draw visual markers in CARLA (needs CARLA running)

`python test_speed_units.py`
Test whether set_desired_speed takes km/h or m/s

### Data Recording and ML

`python init_main_map_registration.py`
Record vehicle telemetry to CSV (needs CARLA running)

`python world_data_analysis.py`
Enrich CSVs and build master training dataset

`python mlmodel_training.py`
Train the Random Forest model

`python vehicle_behavior_analysis.py`
Run real-time inference (needs CARLA running)

---

## Manual OSM Download (When Overpass Is Down)

If the automatic download fails with 504 errors, download manually:
1. Open your browser and go to: https://overpass-turbo.eu
2. Look at the error message in your terminal. 
   Find the line that says `bbox SW=(...) NE=(...)`. 
   Write down the four numbers: south latitude, west longitude, 
   north latitude, east longitude.
3. Delete everything in the query box on the left side of overpass-turbo.
4. Paste this (replace the numbers with yours):

[out:xml][timeout:180];
(
node(SOUTH,WEST,NORTH,EAST);
way(SOUTH,WEST,NORTH,EAST);
relation(SOUTH,WEST,NORTH,EAST);
);
out body;

;
out skel qt;

5. Click **Run** (top left). Wait up to 2 minutes.
6. Click **Export** (top menu).
7. Click **download/copy as raw OSM data**.
8. If the downloaded file has no `.osm` extension, rename it to end in `.osm`.
9. Move the file to: `maps\here_road\here_road.osm` 
   (replace `here_road` with whatever `--name` you used).
10. Re-run your command. 
    The script will find the file and skip the download.

---

## The Machine Learning Pipeline

The ML pipeline is separate from the traffic mirror. 
Run these steps in order after you have recorded at least one driving session.

### Step 1: Record Driving Data

With the traffic mirror running in one terminal, open a second terminal:

python init_main_map_registration.py

This records every vehicle's speed, throttle, brake, steer, and collision status to a CSV file 
in the `DataCSV/` folder. 
It runs for 120 seconds by default. 
Change this by setting `SESSION_DURATION=300` in your `.env` file (300 = 5 minutes).

Record multiple sessions. 
More data produces a better model.

### Step 2: Build the Training Dataset

python world_data_analysis.py

This reads all CSV files in `DataCSV/`, enriches them with derived features 
(speed changes, incident labels, stuck detection), 
and writes a single master file: `DataCSV/dataset_vehicles_enriched_MASTER.csv`.

### Step 3: Train the Model

python mlmodel_training.py

This reads the master CSV, splits by recording session, 
trains a Random Forest classifier, 
and saves the trained model to `traffic_aimodel.pkl`.
It also opens matplotlib windows showing feature importance and confusion matrix. 

### Step 4: Run Real-Time Inference

With the traffic mirror running (or any CARLA world with vehicles):

python vehicle_behavior_analysis.py

This loads the trained model, monitors every vehicle in the simulation,
and draws red arrows above vehicles the model predicts will be involved in an incident. 
Statistics (true positives, false positives, lead time) are saved to `realtime_inference_results.txt`.

---

## Troubleshooting

### "time-out of 15000ms while waiting for the simulator"

The map is too large for the default 15-second timeout. 
The code setsa 120-second timeout for map loading. 
If you still see this error, CARLA may not be running. 
Start it manually:
cd C:\CARLA_0.9.16
CarlaUE4.exe -quality-level=Low

Then retry the command.

### "'python' is not recognized"

Python is not in your system PATH. 
Reinstall Python and check the **"Add Python to PATH"** checkbox during installation.

### "ModuleNotFoundError: No module named 'carla'"

The CARLA Python API is not installed. 
See Step 4 above for how to install the `.whl` file from the CARLA folder.

### "ModuleNotFoundError: No module named 'dotenv'"

Run: `pip install python-dotenv`

### "ModuleNotFoundError: No module named 'pyproj'"

Run: `pip install pyproj`

### "pj_obj_create: Cannot find proj.db"

Find the path of `venv\Lib\site-packages\pyproj\proj_dir\share\proj`

Run: `set PROJ_DATA=C:\...\venv\Lib\site-packages\pyproj\proj_dir\share\proj`
Run: `set PROJ_LIB=C:\...\venv\Lib\site-packages\pyproj\proj_dir\share\proj`

### "ValueError: HERE_API_KEY is not set"

Create or edit your `.env` file and add your HERE API key. 
See Step 6.

### Overpass download fails with 504 errors

The public Overpass servers are temporarily overloaded. 
Either wait 5-10 minutes and try again, or follow the manual download instructions above.

### CARLA window is black or shows a loading screen forever

Your GPU may not have enough memory. 
Try starting CARLA with low quality:
CarlaUE4.exe -quality-level=Low

If it still does not work, your GPU may not be supported. 
CARLA requires a GPU with DirectX 11 support and at least 4 GB of memory.

### Vehicles fall through the road or spawn in the air

This is a known issue with some OpenStreetMap-to-OpenDRIVE conversions.
The geometry repair scripts handle most cases. 
If it persists, try a slightly different `--lat` / `--lon` or `--radius` to get a different OSM extract.

---

## Project Structure

project_root/
|
|-- run_traffic_mirror.py   # Main entry point, runs the full pipeline
|-- mirror_road.py          # Step 1: pick a road from HERE data
|-- provision_map.py        # Step 2: download and convert the map
|-- traffic_mirror.py       # Step 5: the traffic mirror loop
|
|-- here_traffic.py         # HERE API client: fetch, parse, apply traffic
|-- here_archive.py         # Archive HERE responses as evidence
|
|-- geo_transform.py        # Convert lat/lon to CARLA x/y coordinates
|-- map_profile.py          # Map configuration and bounding box math
|-- segment_population.py   # Traffic density model (vehicles per segment)
|
|-- main_map_conversion.py  # Convert .osm to .xodr (OpenDRIVE)
|-- osm_downloader.py       # Download from Overpass API
|-- init_main_map.py        # Load map into CARLA, spawn vehicles
|
|-- find_degenerate_geometry.py     # Scan for broken geometry in .xodr
|-- patch_zero_length_geometry.py   # Fix zero-length geometry elements
|-- find_crosswalk_overflow.py      # Scan for crosswalks past road end
|-- patch_crosswalk_overflow.py     # Fix crosswalk overflow
|
|-- check_map_calibration.py        # Automated calibration pass/fail
|-- verify_map_calibration.py       # Visual calibration markers
|-- test_speed_units.py             # Verify CARLA speed API units
|
|-- init_main_map_registration.py   # Record vehicle telemetry to CSV
|-- world_data_analysis.py          # Enrich CSVs, build training dataset
|-- mlmodel_training.py             # Train Random Forest classifier
|-- model_features.py               # Feature and target column definitions
|-- vehicle_behavior_analysis.py    # Real-time inference with trained model
|
|-- device_traffic_feed.py          # Simulated field device readings
|-- requirements.txt                # Python dependencies
|-- .env                            # Your configuration (not in Git)
|
|-- maps/                           # Generated map files (.osm, .xodr)
|-- DataCSV/                        # Recorded telemetry CSV files
|-- DataHERE/                       # Archived HERE API responses

---

## How It Works (Technical Summary)

### Coordinate System

HERE and OpenStreetMap use WGS84 latitude/longitude 
(degrees on a sphere). 
CARLA uses flat x/y coordinates in metres. 
The `geo_transform` module bridges these two systems 
using the same Transverse Mercator projection that was used to build the road mesh, 
guaranteeing that converted coordinates land exactly on the correct roads.

### Traffic Density Model

Vehicle density per segment is computed from HERE's jam_factor:

density_vehicles_per_km = congestion * JAM_DENSITY_VEH_PER_KM

Where jam_density = 120 vehicles/km. 
At jam_factor = 0 (free flow) the road has zero vehicles. 
At jam_factor = 10 (complete standstill) the road is at maximum capacity.

### Speed Mirroring

Each vehicle's speed is set to the current speed HERE reports for the road segment it is on, 
capped at that segment's free-flow speed. 
The free-flow speed comes from HERE's `freeFlow` field, 
which reflects the measured uncongested speed for that specific road. 
No global speed limit is hardcoded.

### HERE Data Archival

When recording is enabled, every HERE API response is saved as indented JSON with a SHA-256 hash. 
The hash is computed from the exactbytes written to disk, 
allowing an examiner to verify that archived files have not been modified after recording.

---

## References

- CARLA Simulator: https://carla.org/ (version 0.9.16)
- HERE Traffic API v7: https://docs.here.com/traffic-api/
- OpenStreetMap / Overpass API: https://overpass-api.de/
- PROJ library (coordinate transformations): https://proj.org/
