"""Direct port of backend/ml/generateDataset.js — same seed, same drug
catalog, same seasonal/trend/spike construction, so the resulting dataset
(and therefore the trained model's behaviour) matches the original project."""
import json
import random
from datetime import date, timedelta

from app.config import ML_ARTIFACT_DIR

DATASET_SEED = 20260101

DRUGS = [
    {"name": "Paracetamol 500mg", "category": "Analgesic", "base": 45, "seasonPeakDay": 15, "seasonAmplitude": 0.15, "trendPerYear": 0.02, "noisePct": 0.12, "spikeProneness": 0.2},
    {"name": "Amoxicillin 250mg", "category": "Antibiotic", "base": 30, "seasonPeakDay": 15, "seasonAmplitude": 0.45, "trendPerYear": 0.03, "noisePct": 0.15, "spikeProneness": 0.6},
    {"name": "Insulin Glargine 100IU", "category": "Hormone", "base": 12, "seasonPeakDay": 15, "seasonAmplitude": 0.05, "trendPerYear": 0.08, "noisePct": 0.10, "spikeProneness": 0.05},
    {"name": "Azithromycin 500mg", "category": "Antibiotic", "base": 22, "seasonPeakDay": 15, "seasonAmplitude": 0.5, "trendPerYear": 0.03, "noisePct": 0.18, "spikeProneness": 0.8},
    {"name": "Ceftriaxone 1g Injection", "category": "Antibiotic", "base": 10, "seasonPeakDay": 15, "seasonAmplitude": 0.35, "trendPerYear": 0.02, "noisePct": 0.15, "spikeProneness": 0.4},
    {"name": "ORS Sachets", "category": "Rehydration", "base": 60, "seasonPeakDay": 200, "seasonAmplitude": 0.55, "trendPerYear": 0.01, "noisePct": 0.14, "spikeProneness": 0.3},
    {"name": "Metformin 500mg", "category": "Antidiabetic", "base": 35, "seasonPeakDay": 15, "seasonAmplitude": 0.08, "trendPerYear": 0.06, "noisePct": 0.10, "spikeProneness": 0.05},
]

DAYS_PER_DRUG = 580
WEEKDAY_MULTIPLIER = [0.65, 1.0, 1.05, 1.05, 1.05, 1.05, 0.8]  # Sun..Sat (JS Date.getDay() order)


def _day_of_year(d: date) -> int:
    return (d - date(d.year, 1, 1)).days + 1


def _js_day_of_week(d: date) -> int:
    return (d.weekday() + 1) % 7


def _gaussian_noise(scale: float, rand: random.Random) -> float:
    total = sum(rand.random() for _ in range(6))
    return ((total - 3) / 3) * scale


def generate_dataset() -> list:
    rand = random.Random(DATASET_SEED)
    start_date = date.today() - timedelta(days=DAYS_PER_DRUG)
    rows = []

    for drug in DRUGS:
        spike_days_remaining = 0
        spike_multiplier = 1.0

        for t in range(DAYS_PER_DRUG):
            d = start_date + timedelta(days=t)
            doy = _day_of_year(d)

            weekly_factor = WEEKDAY_MULTIPLIER[_js_day_of_week(d)]
            import math
            yearly_factor = 1 + drug["seasonAmplitude"] * math.cos(2 * math.pi * (doy - drug["seasonPeakDay"]) / 365)
            trend_factor = 1 + drug["trendPerYear"] * (t / 365)

            if spike_days_remaining > 0:
                spike_days_remaining -= 1
            elif rand.random() < (drug["spikeProneness"] / 100) * 1.2:
                spike_days_remaining = 3 + int(rand.random() * 4)
                spike_multiplier = 2 + rand.random() * 2.5
            else:
                spike_multiplier = 1.0

            raw_qty = drug["base"] * weekly_factor * yearly_factor * trend_factor * spike_multiplier
            noisy = raw_qty + _gaussian_noise(drug["base"] * drug["noisePct"], rand)
            qty = max(0, round(noisy))

            rows.append({"date": d.isoformat(), "drugName": drug["name"], "category": drug["category"], "qty": qty})

    return rows


def main():
    rows = generate_dataset()
    ML_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ML_ARTIFACT_DIR / "sales_history.json"
    out_path.write_text(json.dumps(rows), encoding="utf-8")
    print(f"Generated {len(rows)} synthetic sales records across {len(DRUGS)} drugs -> {out_path}")


if __name__ == "__main__":
    main()
