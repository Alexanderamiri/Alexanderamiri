"""Generate light_mode.svg and dark_mode.svg: ASCII portrait + neofetch-style profile card.

Static facts live in PROFILE below. Live GitHub numbers come from the GraphQL/REST API.
Run locally:  GITHUB_TOKEN=$(gh auth token) python build.py
"""
from __future__ import annotations

import datetime as dt
import html
import os
import re
import sys
import time
from pathlib import Path

import requests

USER = os.environ.get("USER_NAME", "Alexanderamiri")
TOKEN = os.environ.get("ACCESS_TOKEN") or os.environ.get("GITHUB_TOKEN")
HEADERS = {"Authorization": f"bearer {TOKEN}"} if TOKEN else {}
HERE = Path(__file__).parent
CAREER_START = dt.date(2021, 3, 1)  # first data-scientist role (NAV)

PROFILE = {
    "OS": "macOS, Linux",
    "Host": "DNB - AI Engineers, AI Tech",
    "Kernel": "Senior AI Engineer / ex-astrophysicist",
    "IDE": "Claude Code, Codex, VS Code, IntelliJ",
    "Languages.Programming": "Python, TypeScript, Java, Kotlin, SQL",
    "Languages.Frameworks": "FastAPI, LangGraph, LangChain, React, Remix",
    "Languages.Infra": "AWS, GCP, Kubernetes, Terraform, Docker, Kafka",
    "Languages.Real": "Norwegian, English",
    "Hobbies.Software": "GenAI platforms, multi-agent systems, OSS forks",
    "Hobbies.Community": "javaBin/JavaZone board, Smidig board, speaker",
    "Education": "BSc Astrophysics, University of Oslo",
}
CONTACT = {
    "Email.Personal": "alex@alexanderamiri.com",
    "Email.Work": "Alexander.Amiri@dnb.no",
    "LinkedIn": "alexander-amiri-43256619b",
}

THEMES = {
    "dark": dict(bg="#161b22", fg="#c9d1d9", key="#ffa657", value="#a5d6ff", add="#3fb950", dele="#f85149", cc="#616e7f"),
    "light": dict(bg="#ffffff", fg="#24292f", key="#953800", value="#0a3069", add="#1a7f37", dele="#cf222e", cc="#8c959f"),
}

CHAR_W = 9.7  # ~0.6em at 16px: Consolas with size-adjust 109%, Menlo, DejaVu Sans Mono all land here
LINE_H = 20
FONT_STACK = "Consolas, Menlo, 'DejaVu Sans Mono', 'Liberation Mono', monospace"
LEFT_X = 15
RIGHT_W = 70  # characters available in the right column


# ----------------------------------------------------------------------------- GitHub data
def gql(query: str, variables: dict | None = None) -> dict:
    r = requests.post("https://api.github.com/graphql", json={"query": query, "variables": variables or {}}, headers=HEADERS, timeout=60)
    r.raise_for_status()
    data = r.json()
    if data.get("errors"):
        # Partial results are fine when the only problem is a field the token may not read
        # (the default Actions token cannot see private repos or some per-repo fields).
        if not all(e.get("type") in ("FORBIDDEN", "NOT_FOUND") for e in data["errors"]) or not data.get("data"):
            raise RuntimeError(data["errors"])
        print("warning: partial GraphQL result:", {e["message"] for e in data["errors"]}, file=sys.stderr)
    return data["data"]


def user_summary() -> dict:
    data = gql(
        """
        query($login: String!) {
          user(login: $login) {
            createdAt
            followers { totalCount }
            repositories(ownerAffiliations: OWNER, first: 100) {
              totalCount
              nodes { name isPrivate isFork stargazerCount }
            }
            repositoriesContributedTo(first: 1, contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY, ISSUE]) { totalCount }
          }
        }""",
        {"login": USER},
    )["user"]
    repos = data["repositories"]["nodes"]
    return {
        "created": dt.datetime.fromisoformat(data["createdAt"].replace("Z", "+00:00")),
        "followers": data["followers"]["totalCount"],
        "repos": data["repositories"]["totalCount"],
        "repo_names": [r["name"] for r in repos if r and not r["isFork"]],
        "stars": sum(r.get("stargazerCount") or 0 for r in repos if r),
        "contributed": data["repositoriesContributedTo"]["totalCount"],
    }


def total_contributions(created: dt.datetime) -> int:
    """Lifetime contribution count (includes private/restricted contributions the profile exposes)."""
    total = 0
    start = created
    now = dt.datetime.now(dt.timezone.utc)
    while start < now:
        end = min(start.replace(year=start.year + 1) - dt.timedelta(seconds=1), now)
        d = gql(
            """
            query($login: String!, $from: DateTime!, $to: DateTime!) {
              user(login: $login) { contributionsCollection(from: $from, to: $to) { contributionCalendar { totalContributions } } }
            }""",
            {"login": USER, "from": start.isoformat(), "to": end.isoformat()},
        )
        total += d["user"]["contributionsCollection"]["contributionCalendar"]["totalContributions"]
        start = start.replace(year=start.year + 1)
    return total


def lines_of_code(repo_names: list[str]) -> tuple[int, int]:
    """Sum additions/deletions across owned repos via the code_frequency statistics endpoint."""
    add = dele = 0
    for name in repo_names:
        url = f"https://api.github.com/repos/{USER}/{name}/stats/code_frequency"
        for _ in range(8):
            r = requests.get(url, headers=HEADERS, timeout=60)
            if r.status_code == 202:  # stats being computed
                time.sleep(3)
                continue
            if r.status_code in (204, 403, 404, 422):
                break
            r.raise_for_status()
            for _week, a, d in r.json():
                add += a
                dele += -d
            break
    return add, dele


# ----------------------------------------------------------------------------- rendering
def span(text: str, cls: str | None = None, id_: str | None = None) -> str:
    attrs = "".join(f' {k}="{v}"' for k, v in (("class", cls), ("id", id_)) if v)
    return f"<tspan{attrs}>{html.escape(text)}</tspan>"


def kv(key: str, value: str, width: int = RIGHT_W) -> str:
    """'. Key: ...... value' padded with dots to a fixed width, like Andrew6rant's card."""
    parts = key.split(".")
    key_svg = span(parts[0], "key") + "".join("." + span(p, "key") for p in parts[1:])
    used = 2 + len(key) + 1 + 1 + len(value)  # '. ' key ':' ' ' value
    dots = max(1, width - used - 1)
    return span(". ", "cc") + key_svg + ":" + span(" " + "." * dots + " ", "cc") + span(value, "value")


def header(title: str, width: int = RIGHT_W) -> str:
    rule = "-" + "—" * (width - len(title) - 4) + "-"
    return span(title) + " " + rule


def age(start: dt.date) -> str:
    today = dt.date.today()
    y = today.year - start.year - ((today.month, today.day) < (start.month, start.day))
    m = (today.month - start.month - (today.day < start.day)) % 12
    anchor = dt.date(start.year + y, start.month, 1) + dt.timedelta(days=start.day - 1)
    anchor = anchor.replace(year=start.year + y + (m + start.month - 1) // 12, month=(start.month - 1 + m) % 12 + 1)
    d = (today - anchor).days
    plural = lambda n, u: f"{n} {u}{'s' if n != 1 else ''}"
    return f"{plural(y, 'year')}, {plural(m, 'month')}, {plural(d, 'day')}"


def right_lines(stats: dict) -> list[str]:
    f = lambda n: f"{n:,}"
    lines = [
        header("alexander@amiri"),
        kv("OS", PROFILE["OS"]),
        kv("Uptime", age(CAREER_START) + " in AI"),
        kv("Host", PROFILE["Host"]),
        kv("Kernel", PROFILE["Kernel"]),
        kv("IDE", PROFILE["IDE"]),
        span(". ", "cc"),
        kv("Languages.Programming", PROFILE["Languages.Programming"]),
        kv("Languages.Frameworks", PROFILE["Languages.Frameworks"]),
        kv("Languages.Infra", PROFILE["Languages.Infra"]),
        kv("Languages.Real", PROFILE["Languages.Real"]),
        span(". ", "cc"),
        kv("Hobbies.Software", PROFILE["Hobbies.Software"]),
        kv("Hobbies.Community", PROFILE["Hobbies.Community"]),
        kv("Education", PROFILE["Education"]),
        "",
        header("- Contact"),
        *(kv(k, v) for k, v in CONTACT.items()),
        "",
        header("- GitHub Stats"),
        (
            span(". ", "cc") + span("Repos", "key") + ":" + span(" .... ", "cc") + span(f(stats["repos"]), "value")
            + " {" + span("Contributed", "key") + ": " + span(f(stats["contributed"]), "value") + "} | "
            + span("Stars", "key") + ":" + span(" ........... ", "cc") + span(f(stats["stars"]), "value")
        ),
        (
            span(". ", "cc") + span("Commits", "key") + ":" + span(" ................. ", "cc") + span(f(stats["commits"]), "value")
            + " | " + span("Followers", "key") + ":" + span(" ....... ", "cc") + span(f(stats["followers"]), "value")
        ),
        (
            span(". ", "cc") + span("Lines of Code on GitHub", "key") + ":" + span(" . ", "cc") + span(f(stats["loc"]), "value")
            + " ( " + span(f(stats["add"]), "add") + span("++", "add") + ", " + span(f(stats["dele"]), "dele") + span("--", "dele") + " )"
        ),
    ]
    return lines


def render(theme: dict, art: list[str], right: list[str]) -> str:
    art_w = max(len(l) for l in art)
    right_x = LEFT_X + int(art_w * CHAR_W) + 40
    width = right_x + int((RIGHT_W + 2) * CHAR_W) + LEFT_X
    rows = max(len(art), len(right))
    height = 30 + rows * LINE_H
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" font-family="{FONT_STACK}" width="{width}px" height="{height}px" font-size="16px">',
        "<style>",
        f".key {{fill: {theme['key']};}} .value {{fill: {theme['value']};}} .add {{fill: {theme['add']};}} .dele {{fill: {theme['dele']};}} .cc {{fill: {theme['cc']};}}",
        "text, tspan {white-space: pre;}",
        "</style>",
        f'<rect width="{width}px" height="{height}px" fill="{theme["bg"]}" rx="15"/>',
        f'<text x="{LEFT_X}" y="30" fill="{theme["fg"]}" class="ascii">',
    ]
    for i, line in enumerate(art):
        out.append(f'<tspan x="{LEFT_X}" y="{30 + i * LINE_H}">{html.escape(line)}</tspan>')
    out.append("</text>")
    out.append(f'<text x="{right_x}" y="30" fill="{theme["fg"]}">')
    for i, line in enumerate(right):
        out.append(f'<tspan x="{right_x}" y="{30 + i * LINE_H}">{line}</tspan>')
    out.append("</text>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> None:
    art = (HERE / "ascii.txt").read_text().rstrip("\n").split("\n")
    summary = user_summary()
    commits = total_contributions(summary["created"])
    add, dele = lines_of_code(summary["repo_names"])
    stats = {**summary, "commits": commits, "add": add, "dele": dele, "loc": add - dele}
    right = right_lines(stats)
    longest = max(len(re.sub(r"<[^>]+>", "", html.unescape(l))) for l in right)
    assert longest <= RIGHT_W + 2, f"right column overflows: {longest} > {RIGHT_W}"
    for name, theme in THEMES.items():
        (HERE / f"{name}_mode.svg").write_text(render(theme, art, right))
    print({k: v for k, v in stats.items() if k not in ("repo_names", "created")}, file=sys.stderr)


if __name__ == "__main__":
    main()
