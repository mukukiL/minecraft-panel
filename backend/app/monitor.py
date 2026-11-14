import asyncio
import time
from collections import deque
from pathlib import Path

from app.errors import Problem


class Monitor:
    def __init__(self) -> None:
        self.state = "unknown"
        self.samples: deque[dict[str, float | None]] = deque(maxlen=120)
        self.previous_cpu: tuple[int, int] | None = None

    def resources(self) -> tuple[float | None, float | None]:
        try:
            fields = Path("/proc/stat").read_text().splitlines()[0].split()
            ticks = [int(value) for value in fields[1:9]]
            total, idle = sum(ticks), ticks[3] + ticks[4]
            previous = self.previous_cpu
            self.previous_cpu = total, idle
            cpu = None
            if previous and total > previous[0]:
                cpu = round(100 * (1 - (idle - previous[1]) / (total - previous[0])), 1)
                cpu = max(0.0, min(100.0, cpu))
        except (OSError, ValueError, IndexError):
            cpu = None
        try:
            values = {}
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith(("MemTotal:", "MemAvailable:")):
                    name, value, _ = line.split()
                    values[name] = int(value)
            memory = round(100 * (1 - values["MemAvailable:"] / values["MemTotal:"]), 1)
            memory = max(0.0, min(100.0, memory))
        except (OSError, ValueError, KeyError, ZeroDivisionError):
            memory = None
        return cpu, memory

    async def run(self, adapter) -> None:
        while True:
            try:
                self.state = await adapter.status()
            except Problem:
                self.state = "unknown"
            cpu, memory = self.resources()
            self.samples.append({"time": time.time(), "cpu": cpu, "memory": memory})
            await asyncio.sleep(5)

    def snapshot(self) -> dict:
        return {"state": self.state, "samples": list(self.samples)}
