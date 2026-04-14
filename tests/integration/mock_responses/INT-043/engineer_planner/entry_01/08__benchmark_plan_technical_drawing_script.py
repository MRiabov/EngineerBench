from build123d import Box, TechnicalDrawing


def build():
    TechnicalDrawing(title="Seeded drafting")
    part = Box(6, 6, 2)
    part.label = "environment_fixture"
    return part
