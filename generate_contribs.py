"""
Generate isometric GitHub contribution SVGs for use in a profile README.

Examples:
    python generate_contribs.py --mock
    python generate_contribs.py --user colincode0 --out ./output
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path


GRAPHQL_ENDPOINT = "https://api.github.com/graphql"


PALETTES = {
    "dark": {
        "empty": "#161b22",
        "levels": ["#0e4429", "#006d32", "#26a641", "#39d353"],
        "bg": "transparent",
    },
    "light": {
        "empty": "#ebedf0",
        "levels": ["#9be9a8", "#40c463", "#30a14e", "#216e39"],
        "bg": "transparent",
    },
}

CELL = 12
ANGLE_DEG = 20
GAP = 2
SHADE_LEFT = 0.88
SHADE_RIGHT = 0.74
BASE_COMMIT_HEIGHT = 8
MAX_COMMIT_HEIGHT = 18

LEVEL_MAP = {
    "NONE": 0,
    "FIRST_QUARTILE": 1,
    "SECOND_QUARTILE": 2,
    "THIRD_QUARTILE": 3,
    "FOURTH_QUARTILE": 4,
}

TEXT_COLORS = {
    "dark": {
        "primary": "#e6edf3",
        "secondary": "#7d8590",
        "accent": "#39d353",
    },
    "light": {
        "primary": "#1f2328",
        "secondary": "#59636e",
        "accent": "#216e39",
    },
}

FONT_STACK = '-apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif'

LAST_YEAR_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            contributionCount
            contributionLevel
            date
          }
        }
      }
    }
  }
}
"""


MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass
class Cell:
    week: int
    day: int
    level: int
    count: int
    date_str: str = ""


@dataclass
class Stats:
    total_contributions: int
    day_of_week_totals: list[int]


def generate_mock_data(weeks: int = 53) -> list[Cell]:
    random.seed(42)
    cells: list[Cell] = []
    # Start roughly one year ago from a known Sunday
    epoch = date(2025, 6, 1)
    for w in range(weeks):
        streak = random.random() < 0.15
        for d in range(7):
            is_weekend = d == 0 or d == 6
            if streak:
                base = [0.05, 0.15, 0.30, 0.30, 0.20]
            elif is_weekend:
                base = [0.55, 0.25, 0.12, 0.06, 0.02]
            else:
                base = [0.25, 0.30, 0.25, 0.13, 0.07]
            r = random.random()
            acc = 0.0
            level = 0
            for idx, probability in enumerate(base):
                acc += probability
                if r <= acc:
                    level = idx
                    break
            if level == 0:
                count = 0
            elif level == 1:
                count = random.randint(1, 3)
            elif level == 2:
                count = random.randint(4, 8)
            elif level == 3:
                count = random.randint(9, 15)
            else:
                count = random.randint(16, 28)
            day_date = epoch + timedelta(weeks=w, days=d)
            cells.append(Cell(w, d, level, count, day_date.isoformat()))
    return cells


def stats_from_cells(cells: list[Cell]) -> Stats:
    day_totals = [0, 0, 0, 0, 0, 0, 0]
    total_contributions = 0

    for cell in cells:
        day_totals[cell.day] += cell.count
        total_contributions += cell.count

    return Stats(
        total_contributions=total_contributions,
        day_of_week_totals=day_totals,
    )


def shade(hex_color: str, factor: float) -> str:
    h = hex_color.lstrip("#")
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    r = max(0, min(255, int(r * factor)))
    g = max(0, min(255, int(g * factor)))
    b = max(0, min(255, int(b * factor)))
    return f"#{r:02x}{g:02x}{b:02x}"


def project(x: float, y: float, z: float) -> tuple[float, float]:
    angle = math.radians(ANGLE_DEG)
    sx = (x - y) * math.cos(angle)
    sy = (x + y) * math.sin(angle) - z
    return sx, sy


def cube_faces_svg(gx: int, gy: int, height: int, top_color: str) -> str:
    step = CELL + GAP
    x0 = gx * step
    y0 = gy * step
    size = CELL

    tl = project(x0, y0, height)
    tr = project(x0 + size, y0, height)
    br = project(x0 + size, y0 + size, height)
    bl = project(x0, y0 + size, height)
    top_pts = f"{tl[0]:.2f},{tl[1]:.2f} {tr[0]:.2f},{tr[1]:.2f} {br[0]:.2f},{br[1]:.2f} {bl[0]:.2f},{bl[1]:.2f}"

    polys = [f'<polygon points="{top_pts}" fill="{top_color}"/>']

    if height > 0:
        lf_bb = project(x0, y0 + size, 0)
        lf_bt = project(x0, y0 + size, height)
        lf_tt = project(x0 + size, y0 + size, height)
        lf_tb = project(x0 + size, y0 + size, 0)
        left_pts = f"{lf_bb[0]:.2f},{lf_bb[1]:.2f} {lf_bt[0]:.2f},{lf_bt[1]:.2f} {lf_tt[0]:.2f},{lf_tt[1]:.2f} {lf_tb[0]:.2f},{lf_tb[1]:.2f}"
        polys.append(f'<polygon points="{left_pts}" fill="{shade(top_color, SHADE_LEFT)}"/>')

        rf_bb = project(x0 + size, y0 + size, 0)
        rf_bt = project(x0 + size, y0 + size, height)
        rf_tt = project(x0 + size, y0, height)
        rf_tb = project(x0 + size, y0, 0)
        right_pts = f"{rf_bb[0]:.2f},{rf_bb[1]:.2f} {rf_bt[0]:.2f},{rf_bt[1]:.2f} {rf_tt[0]:.2f},{rf_tt[1]:.2f} {rf_tb[0]:.2f},{rf_tb[1]:.2f}"
        polys.append(f'<polygon points="{right_pts}" fill="{shade(top_color, SHADE_RIGHT)}"/>')

    return "\n".join(polys)


def height_from_count(count: int) -> int:
    if count <= 0:
        return 0
    if count == 1:
        return BASE_COMMIT_HEIGHT

    # One commit should feel meaningful; extra commits add height with
    # diminishing returns instead of forming a strict linear tower.
    extra = math.log2(count) * 3
    return min(MAX_COMMIT_HEIGHT, int(round(BASE_COMMIT_HEIGHT + extra)))


def render_top_right_stats(x: float, y: float, palette_name: str, stats: Stats) -> str:
    text = TEXT_COLORS[palette_name]
    number_size = 34
    label_size = 10
    number_y = y + number_size - 2
    label_y = number_y + 12
    return "\n".join(
        [
            f'<text x="{x:.2f}" y="{number_y:.2f}" text-anchor="end" '
            f'font-family=\'{FONT_STACK}\' font-size="{number_size}" font-weight="700" fill="{text["accent"]}">'
            f"{stats.total_contributions:,}</text>",
            f'<text x="{x:.2f}" y="{label_y:.2f}" text-anchor="end" '
            f'font-family=\'{FONT_STACK}\' font-size="{label_size}" fill="{text["secondary"]}" letter-spacing="0.8">'
            f"TOTAL CONTRIBUTIONS</text>",
        ]
    )


def render_month_labels(cells: list[Cell], palette_name: str, weeks: int) -> str:
    step = CELL + GAP
    max_height = max((height_from_count(cell.count) for cell in cells), default=0)
    label_z = max_height + 8
    text = TEXT_COLORS[palette_name]

    seen_months: set[int] = set()
    month_week_pairs: list[tuple[int, int]] = []

    for cell in sorted(cells, key=lambda c: (c.week, c.day)):
        if not cell.date_str:
            continue
        try:
            m = date.fromisoformat(cell.date_str).month
        except (ValueError, TypeError):
            continue
        if m not in seen_months:
            seen_months.add(m)
            month_week_pairs.append((m, cell.week))

    if not month_week_pairs:
        return ""

    parts = []
    for month_num, week_idx in month_week_pairs:
        gx = week_idx * step + CELL / 2
        sx, sy = project(gx, 0, label_z)
        parts.append(
            f'<text x="{sx:.2f}" y="{sy:.2f}" text-anchor="middle" '
            f'font-family=\'{FONT_STACK}\' font-size="8" fill="{text["secondary"]}">'
            f"{MONTH_ABBR[month_num]}</text>"
        )

    return "\n".join(parts)


def render_bottom_left_stats(x: float, y: float, palette_name: str, stats: Stats) -> str:
    palette = PALETTES[palette_name]
    text = TEXT_COLORS[palette_name]
    parts = []

    chart_x = x
    label_y = y
    chart_y = y - 18
    chart_height = 54
    bar_width = 12
    bar_gap = 4
    title_y = label_y + 20
    tagline_y = title_y + 16
    max_value = max(stats.day_of_week_totals) or 1
    day_labels = ["S", "M", "T", "W", "T", "F", "S"]

    for idx, value in enumerate(stats.day_of_week_totals):
        bar_x = chart_x + idx * (bar_width + bar_gap)
        height = (value / max_value) * chart_height
        bar_top = chart_y - height
        is_peak = value == max_value
        color = palette["levels"][3] if is_peak else palette["levels"][1]
        parts.append(
            f'<rect x="{bar_x:.2f}" y="{bar_top:.2f}" width="{bar_width}" height="{height:.2f}" '
            f'rx="1" fill="{color}"/>'
        )
        parts.append(
            f'<text x="{bar_x + bar_width / 2:.2f}" y="{label_y:.2f}" text-anchor="middle" '
            f'font-family=\'{FONT_STACK}\' font-size="11" fill="{text["secondary"]}">{day_labels[idx]}</text>'
        )

    parts.append(
        f'<text x="{chart_x:.2f}" y="{title_y:.2f}" '
        f'font-family=\'{FONT_STACK}\' font-size="12" fill="{text["secondary"]}" letter-spacing="0.3">'
        f"Most active days</text>"
    )
    parts.append(
        f'<text x="{chart_x:.2f}" y="{tagline_y:.2f}" '
        f'font-family=\'{FONT_STACK}\' font-size="9" fill="{text["secondary"]}">'
        f"Data pulled daily from GitHub.</text>"
    )
    parts.append(
        f'<text x="{chart_x:.2f}" y="{tagline_y + 10:.2f}" '
        f'font-family=\'{FONT_STACK}\' font-size="9" fill="{text["secondary"]}">'
        f"Rolling last-12-month activity.</text>"
    )

    return "\n".join(parts)


def render_svg(cells: list[Cell], palette_name: str, stats: Stats, weeks: int) -> str:
    palette = PALETTES[palette_name]
    sorted_cells = sorted(cells, key=lambda cell: (cell.week + cell.day, cell.level))

    max_height = max((height_from_count(cell.count) for cell in cells), default=0)
    step = CELL + GAP
    corners = [
        project(0, 0, 0),
        project(weeks * step, 0, 0),
        project(0, 7 * step, 0),
        project(weeks * step, 7 * step, 0),
        project(0, 0, max_height),
        project(weeks * step, 0, max_height),
    ]
    xs = [x for x, _ in corners]
    ys = [y for _, y in corners]

    graph_min_x = min(xs)
    graph_max_x = max(xs)
    graph_min_y = min(ys)
    graph_max_y = max(ys)

    pad = 3
    extra_top = 14
    extra_left = 3
    extra_right = 3
    extra_bottom = 40

    min_x = graph_min_x - pad - extra_left
    min_y = graph_min_y - pad - extra_top
    width = (graph_max_x - graph_min_x) + 2 * pad + extra_left + extra_right
    height = (graph_max_y - graph_min_y) + 2 * pad + extra_top + extra_bottom

    tr_anchor_x = graph_max_x
    tr_anchor_y = graph_min_y

    bl_left = graph_min_x
    bl_bottom = graph_max_y - 30

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{min_x:.2f} {min_y:.2f} {width:.2f} {height:.2f}" '
        f'width="{width:.0f}" height="{height:.0f}">'
    ]

    for cell in sorted_cells:
        color = palette["empty"] if cell.level == 0 else palette["levels"][cell.level - 1]
        parts.append(cube_faces_svg(cell.week, cell.day, height_from_count(cell.count), color))

    parts.append(render_month_labels(cells, palette_name, weeks))
    parts.append(render_top_right_stats(tr_anchor_x, tr_anchor_y, palette_name, stats))
    parts.append(render_bottom_left_stats(bl_left, bl_bottom, palette_name, stats))
    parts.append("</svg>")
    return "\n".join(parts)


def github_graphql(token: str, query: str, variables: dict[str, object]) -> dict[str, object]:
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = urllib.request.Request(
        GRAPHQL_ENDPOINT,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "github-readme-generator",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API request failed ({exc.code}): {body}") from exc

    data = json.loads(body)
    if "errors" in data:
        raise RuntimeError(f"GitHub API returned errors: {json.dumps(data['errors'])}")
    return data["data"]


def fetch_last_year_payload(token: str, login: str) -> dict[str, object]:
    data = github_graphql(token, LAST_YEAR_QUERY, {"login": login})
    user = data.get("user")
    if not user:
        raise RuntimeError(f"User '{login}' was not found.")
    return user["contributionsCollection"]


def build_cells_and_days(weeks: list[dict[str, object]]) -> tuple[list[Cell], list[int]]:
    cells: list[Cell] = []
    day_totals = [0, 0, 0, 0, 0, 0, 0]

    for week_index, week in enumerate(weeks):
        # GitHub already returns the days in display order for each week.
        # Preserve that order directly instead of re-deriving weekdays.
        for day_index, day in enumerate(week["contributionDays"]):
            level = LEVEL_MAP[day["contributionLevel"]]
            count = day["contributionCount"]
            date_val = day.get("date", "")

            cells.append(Cell(week=week_index, day=day_index, level=level, count=count, date_str=date_val))
            day_totals[day_index] += count

    return cells, day_totals


def fetch_live_data(token: str, login: str) -> tuple[list[Cell], Stats, int]:
    current_payload = fetch_last_year_payload(token, login)

    weeks = current_payload["contributionCalendar"]["weeks"]
    cells, day_totals = build_cells_and_days(weeks)

    stats = Stats(
        total_contributions=current_payload["contributionCalendar"]["totalContributions"],
        day_of_week_totals=day_totals,
    )
    return cells, stats, len(weeks)


def resolve_defaults() -> tuple[str | None, str | None]:
    user = (
        os.getenv("GITHUB_USER")
        or os.getenv("GITHUB_REPOSITORY_OWNER")
        or os.getenv("GITHUB_ACTOR")
    )
    token = os.getenv("GH_README_TOKEN") or os.getenv("GITHUB_TOKEN")
    return user, token


def main() -> int:
    default_user, default_token = resolve_defaults()

    parser = argparse.ArgumentParser()
    parser.add_argument("--user", default=default_user, help="GitHub username to render")
    parser.add_argument("--token", default=default_token, help="GitHub token for GraphQL access")
    parser.add_argument("--out", default="./output", help="output directory")
    parser.add_argument("--mock", action="store_true", help="render with built-in mock data")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.mock:
        cells = generate_mock_data()
        stats = stats_from_cells(cells)
        weeks = 53
    else:
        if not args.user:
            print("Missing GitHub user. Pass --user or set GITHUB_USER.", file=sys.stderr)
            return 1
        if not args.token:
            print(
                "Missing GitHub token. Set GH_README_TOKEN or GITHUB_TOKEN, or use --mock.",
                file=sys.stderr,
            )
            return 1
        cells, stats, weeks = fetch_live_data(args.token, args.user)

    for palette in ("dark", "light"):
        svg = render_svg(cells, palette, stats, weeks)
        path = out_dir / f"contribs-{palette}.svg"
        path.write_text(svg, encoding="utf-8")
        print(f"wrote {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
