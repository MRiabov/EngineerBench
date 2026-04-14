from build123d import Box


def build():
    part = Box(6, 6, 2)
    part.label = "environment_fixture"
    return part
