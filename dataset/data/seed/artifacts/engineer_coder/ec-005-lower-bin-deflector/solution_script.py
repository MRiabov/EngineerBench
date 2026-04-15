from build123d import Box, BuildPart, Compound


def build() -> Compound:
    with BuildPart() as builder:
        Box(10, 10, 10)
    return Compound(children=[builder.part], label="solution_assembly")
