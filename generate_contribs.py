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
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
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
ANGLE_DEG = 22
GAP = 2
SHADE_LEFT = 0.88
SHADE_RIGHT = 0.74
HEIGHT_SCHEME = [1, 4, 7, 10, 13]

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

YEAR_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionYears
      totalCommitContributions
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

REPOS_QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    repositories(
      first: 100
      after: $cursor
      ownerAffiliations: OWNER
      isFork: false
      orderBy: {field: PUSHED_AT, direction: DESC}
    ) {
      nodes {
        isArchived
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node {
              name
            }
          }
        }
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""


@dataclass
class Cell:
    week: int
    day: int
    level: int


@dataclass
class Stats:
    total_contributions: int
    top_languages: list[tuple[str, float]]
    total_commits: int
    day_of_week_totals: list[int]


MOCK_STATS = Stats(
    total_contributions=1247,
    top_languages=[("TypeScript", 0.42), ("Python", 0.28), ("Rust", 0.18), ("Go", 0.12)],
    total_commits=892,
    day_of_week_totals=[48, 231, 268, 245, 252, 178, 25],
)


def generate_mock_data(weeks: int = 53) -> list[Cell]:
    random.seed(42)
    cells: list[Cell] = []
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
            cells.append(Cell(w, d, level))
    return cells


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


def cube_faces_svg(gx: int, gy: int, level: int, top_color: str) -> str:
    step = CELL + GAP
    x0 = gx * step
    y0 = gy * step
    size = CELL
    height = HEIGHT_SCHEME[level]

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
            f"{stats.total_commits:,}</text>",
            f'<text x="{x:.2f}" y="{label_y:.2f}" text-anchor="end" '
            f'font-family=\'{FONT_STACK}\' font-size="{label_size}" fill="{text["secondary"]}" letter-spacing="0.8">'
            f"TOTAL COMMITS</text>",
        ]
    )


def render_bottom_left_stats(x: float, y: float, palette_name: str, stats: Stats) -> str:
    palette = PALETTES[palette_name]
    text = TEXT_COLORS[palette_name]
    parts = []

    chart_x = x
    label_y = y
    chart_y = y - 14
    chart_height = 34
    bar_width = 9
    bar_gap = 3
    max_value = max(stats.day_of_week_totals) or 1
    day_labels = ["S", "M", "T", "W", "T", "F", "S"]

    parts.append(
        f'<text x="{chart_x:.2f}" y="{chart_y - chart_height - 5:.2f}" '
        f'font-family=\'{FONT_STACK}\' font-size="10" fill="{text["secondary"]}" letter-spacing="0.8">'
        f"MOST ACTIVE DAYS</text>"
    )

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
            f'font-family=\'{FONT_STACK}\' font-size="10" fill="{text["secondary"]}">{day_labels[idx]}</text>'
        )

    return "\n".join(parts)


def render_svg(cells: list[Cell], palette_name: str, stats: Stats, weeks: int) -> str:
    palette = PALETTES[palette_name]
    sorted_cells = sorted(cells, key=lambda cell: (cell.week + cell.day, cell.level))

    max_height = max(HEIGHT_SCHEME)
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
    extra_top = 3
    extra_left = 3
    extra_right = 3
    extra_bottom = 3

    min_x = graph_min_x - pad - extra_left
    min_y = graph_min_y - pad - extra_top
    width = (graph_max_x - graph_min_x) + 2 * pad + extra_left + extra_right
    height = (graph_max_y - graph_min_y) + 2 * pad + extra_top + extra_bottom

    tr_anchor_x = graph_max_x
    tr_anchor_y = graph_min_y

    bl_left = graph_min_x
    bl_bottom = graph_max_y

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{min_x:.2f} {min_y:.2f} {width:.2f} {height:.2f}" '
        f'width="{width:.0f}" height="{height:.0f}">'
    ]

    for cell in sorted_cells:
        color = palette["empty"] if cell.level == 0 else palette["levels"][cell.level - 1]
        parts.append(cube_faces_svg(cell.week, cell.day, cell.level, color))

    parts.append(render_top_right_stats(tr_anchor_x, tr_anchor_y, palette_name, stats))
    parts.append(render_bottom_left_stats(bl_left, bl_bottom, palette_name, stats))
    parts.append("</svg>")
    return "\n".join(parts)


def build_iso_datetime(value: date, end_of_day: bool = False) -> str:
    if end_of_day:
        dt = datetime(value.year, value.month, value.day, 23, 59, 59, tzinfo=timezone.utc)
    else:
        dt = datetime(value.year, value.month, value.day, 0, 0, 0, tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


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


def fetch_range_payload(token: str, login: str, start: date, end: date) -> dict[str, object]:
    data = github_graphql(
        token,
        YEAR_QUERY,
        {
            "login": login,
            "from": build_iso_datetime(start),
            "to": build_iso_datetime(end, end_of_day=True),
        },
    )
    user = data.get("user")
    if not user:
        raise RuntimeError(f"User '{login}' was not found.")
    return user["contributionsCollection"]


def fetch_language_totals(token: str, login: str) -> Counter[str]:
    totals: Counter[str] = Counter()
    cursor: str | None = None

    while True:
        data = github_graphql(token, REPOS_QUERY, {"login": login, "cursor": cursor})
        user = data.get("user")
        if not user:
            raise RuntimeError(f"User '{login}' was not found.")

        repositories = user["repositories"]
        for repo in repositories["nodes"]:
            if repo["isArchived"]:
                continue
            for edge in repo["languages"]["edges"]:
                totals[edge["node"]["name"]] += edge["size"]

        page_info = repositories["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        cursor = page_info["endCursor"]

    return totals


def build_cells_and_days(weeks: list[dict[str, object]]) -> tuple[list[Cell], list[int]]:
    cells: list[Cell] = []
    day_totals = [0, 0, 0, 0, 0, 0, 0]

    for week_index, week in enumerate(weeks):
        for day in week["contributionDays"]:
            level = LEVEL_MAP[day["contributionLevel"]]
            count = day["contributionCount"]
            contributed_on = date.fromisoformat(day["date"])
            sunday_first_index = 0 if contributed_on.weekday() == 6 else contributed_on.weekday() + 1

            cells.append(Cell(week=week_index, day=sunday_first_index, level=level))
            day_totals[sunday_first_index] += count

    return cells, day_totals


def normalize_languages(totals: Counter[str], top_n: int = 4) -> list[tuple[str, float]]:
    if not totals:
        return [("No repos", 1.0)]

    top = totals.most_common(top_n)
    total_size = sum(size for _, size in top) or 1
    return [(name, size / total_size) for name, size in top]


def fetch_live_data(token: str, login: str) -> tuple[list[Cell], Stats, int]:
    today = date.today()
    # GitHub validates contribution windows strictly; keeping the range a
    # little under a full year avoids occasional off-by-one rejections.
    rolling_start = today - timedelta(days=363)

    current_payload = fetch_range_payload(token, login, rolling_start, today)
    contribution_years = current_payload["contributionYears"]
    total_commits = 0

    for year in contribution_years:
        year_start = max(date(year, 1, 1), rolling_start)
        year_end = min(date(year, 12, 31), today)
        if year_start > year_end:
            continue
        year_payload = fetch_range_payload(token, login, year_start, year_end)
        total_commits += year_payload["totalCommitContributions"]

    weeks = current_payload["contributionCalendar"]["weeks"]
    cells, day_totals = build_cells_and_days(weeks)
    language_totals = fetch_language_totals(token, login)

    stats = Stats(
        total_contributions=current_payload["contributionCalendar"]["totalContributions"],
        top_languages=normalize_languages(language_totals),
        total_commits=total_commits,
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
        stats = MOCK_STATS
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
