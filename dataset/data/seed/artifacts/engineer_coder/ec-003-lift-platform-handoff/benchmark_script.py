from build123d import Align, Box, Compound, Location

from utils.metadata import CompoundMetadata, PartMetadata


def build():
    """Benchmark-owned fixture: sliding lift platform."""
    platform = Box(80.0, 160.0, 8.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    platform = platform.move(Location((40.0, 0.0, 120.0)))
    platform.label = "lift_platform"
    platform.metadata = PartMetadata(material_id="aluminum_6061", fixed=False)

    assembly = Compound(children=[platform])
    assembly.label = "benchmark_environment"
    assembly.metadata = CompoundMetadata()
    return assembly
