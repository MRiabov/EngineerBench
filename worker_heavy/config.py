import tempfile
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from shared.simulation.smoke_mode import resolve_default_smoke_test_mode


class WorkerSettings(BaseSettings):
    """Configuration settings for the Problemologist Worker (Heavy)."""

    is_integration_test: bool = Field(default=False, alias="IS_INTEGRATION_TEST")

    # Heavy worker doesn't strictly need skills sync but we keep it for consistency if needed
    skills_dir_override: str | None = Field(default=None, alias="SKILLS_DIR")

    # Defaults to None so we can apply logic in validator
    smoke_test_mode: bool = Field(default=False, alias="SMOKE_TEST_MODE")

    @model_validator(mode="after")
    def adjust_smoke_test_mode(self) -> "WorkerSettings":
        """Default smoke_test_mode to True if in integration test and not explicitly set."""
        self.smoke_test_mode = resolve_default_smoke_test_mode(
            integration_enabled=self.is_integration_test
        )
        return self

    git_repo_url: str | None = Field(default=None, alias="GIT_REPO_URL")
    git_pat: str | None = Field(default=None, alias="GIT_PAT")

    controller_url: str | None = Field(default=None, alias="CONTROLLER_URL")
    sessions_dir: str | None = Field(default=None, alias="WORKER_SESSIONS_DIR")

    @property
    def skills_dir(self) -> Path:
        """Get the effective skills directory."""
        if self.skills_dir_override:
            return Path(self.skills_dir_override)

        if self.is_integration_test:
            return Path(tempfile.gettempdir()) / "problemologist_skills"

        app_skills = Path("/app/.agents/skills")
        try:
            if app_skills.exists():
                return app_skills
            return Path("./.agents/skills").absolute()
        except Exception:
            return Path("./.agents/skills").absolute()

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = WorkerSettings()
