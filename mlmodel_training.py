import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import confusion_matrix, classification_report, accuracy_score
import joblib

from model_features import MODEL_FEATURES, TARGET_COLUMN


df = pd.read_csv('.\\DataCSV\\dataset_vehicles_enriched_MASTER.csv')

X = df[MODEL_FEATURES]
y = df['incident_detected']

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

print("Training model to predict risks...")

# Random Forest --- due to its precision for traffic systems
model = RandomForestClassifier(n_estimators=100, max_depth=15, min_samples_leaf=5, random_state=42)
model.fit(X_train, y_train)

y_pred = model.predict(X_test)

print("\n--- MODEL RESULTS ---")
print(f"Accuracy: {accuracy_score(y_test, y_pred):.2f}")
print("\nClassification Report:")
print(classification_report(y_test, y_pred))

importances = model.feature_importances_
plt.figure(figsize=(10, 6))
sns.barplot(x=importances, y=MODEL_FEATURES, palette='viridis')
plt.title('Feature Importance')
plt.xlabel('Relative Importance')
plt.show()


cm = confusion_matrix(y_test, y_pred)
plt.figure(figsize=(8, 6))
sns.heatmap(cm, annot=True, fmt='d', cmap='Blues')
plt.title('Confusion Matrix: Incident Prediction')
plt.xlabel('RF Prediction')
plt.ylabel('CARLA implementation')
plt.show()


joblib.dump(model, 'traffic_aimodel.pkl')