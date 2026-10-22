
import os
import csv
import random

# =========================
# Config
# =========================
RANDOM_SEED = 42
NUM_TEMPLATES = 3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_PATH = os.path.join(BASE_DIR, "..", "data", "single_function_v1.2.csv")
TEMPLATE_DIR = os.path.join(BASE_DIR, "..", "template", "fixtxt")
OUTPUT_DIR = os.path.join(BASE_DIR, "..", "result", "defects4j")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "AAArandom_templates.csv")

# =========================
# Init
# =========================
random.seed(RANDOM_SEED)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# =========================
# Load templates (ONLY filenames)
# =========================
templates = [
    os.path.splitext(f)[0]   # remove .txt
    for f in os.listdir(TEMPLATE_DIR)
    if f.lower().endswith(".txt")
]

print(f"Loaded {len(templates)} templates:")
print(templates)

if len(templates) < NUM_TEMPLATES:
    raise ValueError("Not enough templates for sampling!")

# =========================
# Load slugs
# =========================
slugs = []
with open(DATA_PATH, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        slugs.append(row["slug"])

print(f"Loaded {len(slugs)} bugs.")

# =========================
# Generate random assignment
# =========================
results = []

for slug in slugs:
    selected = random.sample(templates, NUM_TEMPLATES)

    results.append({
        "slug": slug,
        "template1": selected[0],
        "template2": selected[1],
        "template3": selected[2],
    })

# =========================
# Save CSV
# =========================
with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=["slug", "template1", "template2", "template3"]
    )
    writer.writeheader()
    writer.writerows(results)

print(f"Saved to: {OUTPUT_FILE}")

