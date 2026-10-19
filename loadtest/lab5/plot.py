"""
График «до / после» для POST /orders/create.
Данные - время ответа в секундах, по одному числу на строку (curl -w "%{time_total}").
Запуск из корня проекта: python loadtest/lab5/plot.py
"""
import matplotlib
matplotlib.use("Agg")  # рисуем сразу в файл, без окна
import matplotlib.pyplot as plt

RUNS = {
    "до Celery": "loadtest/lab5/before.txt",
    "с Celery": "loadtest/lab5/after.txt",
}
COLORS = {"до Celery": "tab:red", "с Celery": "tab:green"}


def read_ms(path):
    """Время ответа каждого запроса в миллисекундах."""
    with open(path) as f:
        return [float(line) * 1000 for line in f if line.strip()]


data = {name: read_ms(path) for name, path in RUNS.items()}
averages = {name: sum(times) / len(times) for name, times in data.items()}

fig, (left, right) = plt.subplots(1, 2, figsize=(11, 4.5))

# Слева - среднее время ответа.
bars = left.bar(list(averages), list(averages.values()), color=list(COLORS.values()))
left.bar_label(bars, labels=[f"{ms:.0f} мс" for ms in averages.values()])
left.set_title("Среднее время ответа (10 запросов)")
left.set_ylabel("мс")

# Справа - каждый запрос. Шкала логарифмическая: 14 мс на одном
# графике с 4000 мс в обычной шкале сливаются с нулём.
for name, times in data.items():
    right.plot(range(1, len(times) + 1), times, marker="o", label=name, color=COLORS[name])
right.set_yscale("log")
right.set_title("Каждый запрос (логарифмическая шкала)")
right.set_xlabel("номер запроса")
right.set_ylabel("мс")
right.grid(alpha=0.3)
right.legend()

fig.suptitle("POST /orders/create: время ответа")
fig.tight_layout()
fig.savefig("loadtest/lab5/orders_time.png", dpi=100)
for name, ms in averages.items():
    print(f"{name}: среднее {ms:.1f} мс, мин {min(data[name]):.1f}, макс {max(data[name]):.1f}")
print("Сохранено: loadtest/lab5/orders_time.png")
