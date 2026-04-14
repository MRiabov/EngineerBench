from build123d import Box, BuildPart


def build():
    with BuildPart() as builder:
        Box(10, 10, 10)
    return builder.part


result = build()
