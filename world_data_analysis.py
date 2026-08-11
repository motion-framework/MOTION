import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import os
import glob

INPUT_FOLDER = '.\\DataCSV\\'
all_raw_files = glob.glob(os.path.join(INPUT_FOLDER, 'dataset_collisions*.csv'))
FINAL_MASTER_FILE = '.\\DataCSV\\dataset_vehicles_enriched_MASTER.csv'

JAM_VELOCITY = 0.5    
REGISTERS_WINDOW = 10 
PROXIMITY_THRESHOLD = 15.0

def analyze_scenario(file_path):
    df = pd.read_csv(file_path)
    if len(df) < REGISTERS_WINDOW: return None

    df['is_stuck'] = df.groupby('v_id')['speed_kmh'].transform(
        lambda x: x.rolling(window=REGISTERS_WINDOW).max() < JAM_VELOCITY
    ).fillna(0).astype(int)

    accident_spots = df[df['collision'] == 1][['x', 'y']].drop_duplicates()

    def check_jam_cause(row, accidents, threshold):
        if row['is_stuck'] == 0: return 0
        if row['collision'] == 1: return 0 
        for _, acc in accidents.iterrows():
            dist = np.sqrt((row['x'] - acc['x'])**2 + (row['y'] - acc['y'])**2)
            if dist < threshold: return 1
        return 0

    if not accident_spots.empty:
        df['jam_by_crash'] = df.apply(lambda r: check_jam_cause(r, accident_spots, PROXIMITY_THRESHOLD), axis=1)
    else:
        df['jam_by_crash'] = 0

    df['jam_normal'] = ((df['is_stuck'] == 1) & (df['jam_by_crash'] == 0) & (df['collision'] == 0)).astype(int)

    df['base_incident'] = ((df['collision'] == 1) | (df['is_stuck'] == 1)).astype(int)

    df['incident_detected'] = df.groupby('v_id')['base_incident'].transform(
    lambda x: x.rolling(window=20, min_periods=1).max()
    ).shift(-15).fillna(0).astype(int) 

    df['delta_speed'] = df.groupby('v_id')['speed_kmh'].diff()
    df.loc[df['delta_speed'] < -8, 'incident_detected'] = 1
    
    return df

all_scenarios = []

for f in all_raw_files:
    print(f"Enriching file data: {os.path.basename(f)}...")
    enriched = analyze_scenario(f)
    if enriched is not None:
        all_scenarios.append(enriched)

if all_scenarios:
    master_df = pd.concat(all_scenarios, axis=0, ignore_index=True)
    master_df.to_csv(FINAL_MASTER_FILE, index=False)
    
    print(f"\nProcess finished. Master dataset saved in: {FINAL_MASTER_FILE}")
    print(f"Total registers to train AI: {len(master_df)}")

    plt.figure(figsize=(10, 8))
    cols_to_corr = ['speed_kmh', 'throttle', 'brake', 'steer', 'collision', 'jam_normal', 'incident_detected']
    sns.heatmap(master_df[cols_to_corr].corr(), annot=True, cmap='coolwarm', fmt='.2f')
    plt.title('Global Correlation Matrix (All scenarios)')
    plt.show()
else:
    print(" No CSV files to process.")