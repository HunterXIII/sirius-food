"""
Графики «до / после» по CSV, которые сохранил Locust (--csv).
Запуск из корня проекта: python loadtest/plot.py
Нужен matplotlib: pip install matplotlib
"""
import csv

import matplotlib
matplotlib.use("Agg")  # рисуем сразу в файл, без окна
import matplotlib.pyplot as plt

RUNS = {
    "до кеша": "loadtest/before",
    "с кешем": "loadtest/final",
}


def read_history(folder):
    """Секунды от начала, RPS, медиана и 95-й перцентиль по каждой секунде."""
    seconds, rps, p50, p95 = [], [], [], []
    with open(f"{folder}/locust_stats_history.csv") as f:
        rows = [row for row in csv.DictReader(f) if row["Name"] == "Aggregated"]
    start = int(rows[0]["Timestamp"])
    for row in rows:
        if row["50%"] == "N/A":
            continue
        seconds.append(int(row["Timestamp"]) - start)
        rps.append(float(row["Requests/s"]))
        p50.append(float(row["50%"]))
        p95.append(float(row["95%"]))
    return seconds, rps, p50, p95


data = {name: read_history(folder) for name, folder in RUNS.items()}

plt.figure(figsize=(9, 4.5))
for name, (seconds, rps, _, _) in data.items():
    plt.plot(seconds, rps, label=name)
plt.title("GET /menu/items: запросов в секунду (500 пользователей, +10 в секунду)")
plt.xlabel("секунды от начала теста")
plt.ylabel("RPS")
plt.grid(alpha=0.3)
plt.legend()
plt.tight_layout()
plt.savefig("loadtest/rps.png", dpi=100)

plt.figure(figsize=(9, 4.5))
for name, (seconds, _, p50, p95) in data.items():
    line, = plt.plot(seconds, p95, label=f"{name}, 95%")
    plt.plot(seconds, p50, "--", color=line.get_color(), label=f"{name}, медиана")
plt.title("GET /menu/items: время ответа")
plt.xlabel("секунды от начала теста")
plt.ylabel("мс")
plt.grid(alpha=0.3)
plt.legend()
plt.tight_layout()
plt.savefig("loadtest/latency.png", dpi=100)
print("Сохранено: loadtest/rps.png, loadtest/latency.png")
