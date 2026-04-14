"""Simulation configuration constants."""

from pydantic_settings import BaseSettings


class SimulationSettings(BaseSettings):
    """Simulation configuration settings."""

    # Hard cap on simulation time per architecture spec
    max_simulation_time_seconds: float = 30.0
    # Standard simulation step for MuJoCo (2ms)
    simulation_step_s: float = 0.002

    class Config:
        env_prefix = "SIM_"


simulation_settings = SimulationSettings()
