# ruff: noqa
from build123d import *  # noqa: F403, F405


def build():
    b = Box(10, 10, 10)
    b.label = "part1"
    return b
