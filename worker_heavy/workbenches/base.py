from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Protocol

from build123d import Compound, Part
from deprecated import deprecated

from shared.workers.workbench_models import (
    CostBreakdown,
    ManufacturingConfig,
    WorkbenchContext,
    WorkbenchResult,
)

# Functional interface for workbench analysis
AnalyzeFunction = Callable[[Part | Compound, ManufacturingConfig, int], WorkbenchResult]


class WorkbenchAnalyzer(Protocol):
    """
    Protocol for functional workbench analysis.
    """

    def __call__(
        self, part: Part | Compound, config: ManufacturingConfig, quantity: int = 1
    ) -> WorkbenchResult: ...


class Workbench(ABC):
    """
    Abstract Base Class for all Workbenches in the Agentic CAD Environment.
    A Workbench defines a set of constraints and a cost model for a specific
    manufacturing or assembly process.
    """

    @abstractmethod
    @deprecated(
        "Use validate_geometry, will be removed soon. Not to be "
        "confused with agents' validate."
    )
    def validate(self, part: Part) -> list[Exception | str]:
        """
        Validates the part against the workbench constraints.

        Args:
            part: The build123d Part to validate.

        Returns:
            A list of violations (strings or exceptions). If empty, the part is valid.
        """
        pass

    def validate_geometry(self, part: Part) -> list[Exception | str]:
        """
        Alias for validate, as per spec requirements.
        """
        return self.validate(part)

    @abstractmethod
    def calculate_cost(
        self,
        part: Part,
        quantity: int = 1,
        context: WorkbenchContext | None = None,
    ) -> CostBreakdown:
        """
        Calculates the cost of producing the part according to this workbench's cost model.

        Args:
            part: The build123d Part to cost.
            quantity: The number of parts to produce.
            context: Optional context for tracking reused parts across an assembly.

        Returns:
            The calculated cost as a CostBreakdown model.
        """
        pass
