from __future__ import annotations

import math
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH = 2500
HEIGHT = 1480

BACKGROUND = (247, 249, 252, 255)
TITLE = (34, 41, 56, 255)
SUBTITLE = (108, 116, 132, 255)
BODY = (66, 75, 89, 255)
BENCHMARK = (59, 130, 246, 255)
ENGINEER = (34, 197, 94, 255)
REVIEW = (245, 158, 11, 255)
FILL = (255, 255, 255, 255)
FILL_BENCH = (233, 241, 255, 255)
FILL_ENG = (235, 250, 241, 255)
FILL_REVIEW = (255, 248, 229, 255)
LOOP = (237, 137, 54, 255)

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"


def load_font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size=size)
    except Exception:
        return ImageFont.load_default()


def center_text(draw: ImageDraw.ImageDraw, box, text, font, fill):
    left, top, right, bottom = box
    bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=6, align="center")
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = left + (right - left - w) / 2
    y = top + (bottom - top - h) / 2
    draw.multiline_text((x, y), text, font=font, fill=fill, spacing=6, align="center")


def wrap_label(text: str, width: int) -> str:
    return textwrap.fill(
        text, width=width, break_long_words=False, break_on_hyphens=False
    )


def rounded_box(draw, box, outline, fill, width=4, radius=18):
    draw.rounded_rectangle(box, radius=radius, outline=outline, width=width, fill=fill)


def arrow_line(draw, start, end, *, fill, width=5, arrow_size=18):
    draw.line([start, end], fill=fill, width=width)
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    angle = math.atan2(dy, dx)
    left = (
        end[0] - arrow_size * math.cos(angle) + arrow_size * 0.55 * math.sin(angle),
        end[1] - arrow_size * math.sin(angle) - arrow_size * 0.55 * math.cos(angle),
    )
    right = (
        end[0] - arrow_size * math.cos(angle) - arrow_size * 0.55 * math.sin(angle),
        end[1] - arrow_size * math.sin(angle) + arrow_size * 0.55 * math.cos(angle),
    )
    draw.polygon([end, left, right], fill=fill)


def bezier_points(p0, p1, p2, p3, steps=40):
    points = []
    for i in range(steps + 1):
        t = i / steps
        mt = 1 - t
        x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
        y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
        points.append((x, y))
    return points


def curved_arrow(draw, p0, p1, p2, p3, *, fill, width=5, arrow_size=18):
    points = bezier_points(p0, p1, p2, p3)
    draw.line(points, fill=fill, width=width)
    end = points[-1]
    prev = points[-2]
    arrow_line(draw, prev, end, fill=fill, width=width, arrow_size=arrow_size)


def loop_arrow(draw, left, right, top, *, fill, width=5):
    # Loop that rises above the node and returns to the previous node.
    p0 = (left, top)
    p1 = (left - 35, top - 110)
    p2 = (right + 35, top - 110)
    p3 = (right, top)
    curved_arrow(draw, p0, p1, p2, p3, fill=fill, width=width, arrow_size=16)


def render(output: Path):
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(canvas, "RGBA")

    title_font = load_font(FONT, 38)
    subtitle_font = load_font(FONT, 23)
    node_title_font = load_font(FONT, 24)
    node_enum_font = load_font(MONO, 18)
    small_font = load_font(FONT, 18)

    draw.text(
        (WIDTH / 2, 54),
        "Agent Workflow Graph",
        font=title_font,
        fill=TITLE,
        anchor="ma",
    )
    draw.text(
        (WIDTH / 2, 106),
        "Benchmark on the first line, engineering on the second, with reviewer loops back to the previous node",
        font=subtitle_font,
        fill=SUBTITLE,
        anchor="ma",
    )

    box_w = 320
    box_h = 136
    top_y = 320
    bottom_y = 790

    benchmark_x = [360, 920, 1480, 2040]
    engineer_x = [360, 920, 1480, 2040]

    benchmark_nodes = [
        ("Benchmark Planner", "benchmark_planner", BENCHMARK, FILL_BENCH),
        ("Benchmark Plan Reviewer", "benchmark_plan_reviewer", REVIEW, FILL_REVIEW),
        ("Benchmark Coder", "benchmark_coder", BENCHMARK, FILL_BENCH),
        ("Benchmark Reviewer", "benchmark_reviewer", REVIEW, FILL_REVIEW),
    ]
    engineer_nodes = [
        ("Engineering Planner", "engineer_planner", ENGINEER, FILL_ENG),
        ("Engineering Plan Reviewer", "engineer_plan_reviewer", REVIEW, FILL_REVIEW),
        ("Engineering Coder", "engineer_coder", ENGINEER, FILL_ENG),
        (
            "Engineering Execution Reviewer",
            "engineer_execution_reviewer",
            REVIEW,
            FILL_REVIEW,
        ),
    ]

    def draw_node(cx, cy, title, enum_name, outline, fill):
        box = (cx - box_w / 2, cy - box_h / 2, cx + box_w / 2, cy + box_h / 2)
        rounded_box(draw, box, outline, fill, width=4, radius=18)
        title_text = wrap_label(title, 19)
        enum_text = wrap_label(enum_name, 24)
        title_bbox = draw.multiline_textbbox(
            (0, 0), title_text, font=node_title_font, spacing=4, align="center"
        )
        enum_bbox = draw.multiline_textbbox(
            (0, 0), enum_text, font=node_enum_font, spacing=3, align="center"
        )
        title_h = title_bbox[3] - title_bbox[1]
        enum_h = enum_bbox[3] - enum_bbox[1]
        total_h = title_h + 8 + enum_h
        top = cy - total_h / 2
        draw.multiline_text(
            (cx, top),
            title_text,
            font=node_title_font,
            fill=BODY,
            anchor="ma",
            spacing=4,
            align="center",
        )
        draw.multiline_text(
            (cx, top + title_h + 8),
            enum_text,
            font=node_enum_font,
            fill=SUBTITLE,
            anchor="ma",
            spacing=3,
            align="center",
        )
        return box

    benchmark_boxes = [
        draw_node(x, top_y, *node) for x, node in zip(benchmark_x, benchmark_nodes)
    ]
    engineer_boxes = [
        draw_node(x, bottom_y, *node) for x, node in zip(engineer_x, engineer_nodes)
    ]

    # Top row connections.
    for i in range(3):
        right = benchmark_boxes[i][2]
        left = benchmark_boxes[i + 1][0]
        y = top_y
        arrow_line(
            draw,
            (right + 8, y),
            (left - 8, y),
            fill=(70, 78, 92, 255),
            width=5,
            arrow_size=16,
        )

    # Transition from benchmark to engineering.
    start = (benchmark_boxes[-1][2], top_y + box_h / 2)
    end = (engineer_boxes[0][0], bottom_y - box_h / 2)
    curved_arrow(
        draw,
        (start[0] + 8, start[1] + 10),
        (start[0] + 180, start[1] + 140),
        (end[0] - 180, end[1] - 140),
        (end[0] - 8, end[1] - 10),
        fill=(70, 78, 92, 255),
        width=5,
        arrow_size=16,
    )
    draw.text(
        ((start[0] + end[0]) / 2 + 130, (start[1] + end[1]) / 2 + 48),
        "handoff",
        font=small_font,
        fill=SUBTITLE,
        anchor="mm",
    )

    # Bottom row connections.
    for i in range(3):
        right = engineer_boxes[i][2]
        left = engineer_boxes[i + 1][0]
        y = bottom_y
        arrow_line(
            draw,
            (right + 8, y),
            (left - 8, y),
            fill=(70, 78, 92, 255),
            width=5,
            arrow_size=16,
        )

    # Loop arrows above the reviewer nodes.
    loop_arrow(
        draw,
        benchmark_boxes[1][0] + 10,
        benchmark_boxes[0][2] - 10,
        top_y - box_h / 2 - 18,
        fill=LOOP,
        width=5,
    )
    loop_arrow(
        draw,
        benchmark_boxes[3][0] + 10,
        benchmark_boxes[2][2] - 10,
        top_y - box_h / 2 - 18,
        fill=LOOP,
        width=5,
    )
    loop_arrow(
        draw,
        engineer_boxes[1][0] + 10,
        engineer_boxes[0][2] - 10,
        bottom_y - box_h / 2 - 18,
        fill=LOOP,
        width=5,
    )
    loop_arrow(
        draw,
        engineer_boxes[3][0] + 10,
        engineer_boxes[2][2] - 10,
        bottom_y - box_h / 2 - 18,
        fill=LOOP,
        width=5,
    )

    canvas.save(output)


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    render(here.parent / "academic-submission" / "agent_workflow_two_line.png")
