# ruff: noqa
from build123d import *  # noqa: F403, F405


def build():
    b1 = Box(10, 10, 10)
    b1.label = "part1"
    b2 = Box(5, 5, 5).translate((20, 0, 0))
    b2.label = "part2"
    return b1 + b2
