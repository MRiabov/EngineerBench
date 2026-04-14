from shared.models.simulation import SimulationMetrics


class MetricCollector:
    """Handles gathering and resetting simulation metrics."""

    def __init__(self):
        self.metrics = SimulationMetrics()

    def reset(self):
        """Reset all metrics for a new run."""
        self.metrics = SimulationMetrics()

    def update(self, delta_time: float, energy: float, velocity: float):
        """Update metrics with new values."""
        self.metrics.total_time += delta_time
        self.metrics.total_energy += energy
        self.metrics.max_velocity = max(self.metrics.max_velocity, velocity)

    def add_event(self, event_type: str, data: dict):
        """Add an event to the metrics."""
        self.metrics.events.append(
            {"type": event_type, "time": self.metrics.total_time, "data": data}
        )

    def get_metrics(self) -> SimulationMetrics:
        """Return the collected metrics."""
        return self.metrics
