"""Programmatic SVG dashboard. Every dynamic value passes through xml_escape()."""
from __future__ import annotations

from typing import Any

from src.health.statuses import (
    COMPLIANT, CONFIGURED, CRITICAL, EXCLUDED, FAILED, HEALTHY, NO_CI, NON_COMPLIANT,
    NOT_APPLICABLE, NOT_CONFIGURED, OK, UNKNOWN, WARNING,
)
from src.utils.text import truncate, xml_escape

WIDTH = 1200
MARGIN = 40
BG, PANEL, BORDER, TRACK = "#070707", "#111111", "#2e2e2e", "#1f1f1f"
TEXT, MUTED, DIM = "#f4f4f4", "#9b9b9b", "#5f5f5f"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
SANS = "Helvetica, Arial, sans-serif"
ROW_HEIGHT = 26
HEADER_HEIGHT = 132
METRICS_Y, METRICS_H = 152, 100
VIZ_Y, VIZ_H = 274, 232
TABLE_Y = VIZ_Y + VIZ_H + 22

LABELS = {
    HEALTHY: "HEALTHY", WARNING: "WARNING", FAILED: "FAILED", CRITICAL: "CRITICAL", NO_CI: "NO CI",
    UNKNOWN: "UNKNOWN", NOT_APPLICABLE: "N/A", OK: "OK", CONFIGURED: "CONFIGURED",
    NOT_CONFIGURED: "NOT SET", COMPLIANT: "COMPLIANT", NON_COMPLIANT: "NON-COMPLIANT", EXCLUDED: "EXCLUDED",
}
# fill, stroke, dash, text colour. Monochrome: meaning is carried by fill, outline and dash.
BADGE = {
    HEALTHY: ("none", "#ffffff", None, TEXT),
    COMPLIANT: ("none", "#ffffff", None, TEXT),
    CONFIGURED: ("none", "#ffffff", None, TEXT),
    OK: ("none", "#ffffff", None, TEXT),
    WARNING: ("none", "#c8c8c8", "4 3", "#c8c8c8"),
    NON_COMPLIANT: ("none", "#c8c8c8", "4 3", "#c8c8c8"),
    FAILED: ("#ffffff", "#ffffff", None, "#000000"),
    CRITICAL: ("#ffffff", "#ffffff", None, "#000000"),
    NO_CI: ("none", "#7a7a7a", None, MUTED),
    UNKNOWN: ("none", "#7a7a7a", "1 3", MUTED),
    NOT_APPLICABLE: ("none", "#3a3a3a", None, DIM),
    NOT_CONFIGURED: ("none", "#3a3a3a", None, DIM),
    EXCLUDED: ("none", "#3a3a3a", None, DIM),
}
OVERALL_ORDER = {FAILED: 0, UNKNOWN: 1, WARNING: 2, NO_CI: 3, HEALTHY: 4, NOT_APPLICABLE: 5}
SEGMENTS = [
    ("HEALTHY", "healthy", "#cfcfcf"), ("WARNING", "warning", "#8a8a8a"), ("FAILED", "failed", "#ffffff"),
    ("NO CI", "no_ci", "#5a5a5a"), ("UNKNOWN", "unknown", "#363636"), ("N/A", "not_applicable", "#222222"),
]


def _n(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.1f}".rstrip("0").rstrip(".")
    return str(value)


def _pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.1f}%"


def _text(x, y, value, *, size=13, fill=TEXT, weight="400", anchor="start", family=SANS, spacing=None) -> str:
    spacing_attr = f' letter-spacing="{spacing}"' if spacing else ""
    return (f'<text x="{_n(x)}" y="{_n(y)}" font-family="{family}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}"{spacing_attr}>{xml_escape(value)}</text>')


def _badge(x, y, status: str, width: int = 112) -> str:
    fill, stroke, dash, text_fill = BADGE.get(status, BADGE[UNKNOWN])
    label = LABELS.get(status, str(status).replace("_", " "))
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<rect x="{_n(x)}" y="{_n(y)}" width="{width}" height="20" rx="10" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1.2"{dash_attr}/>'
            f'<text x="{_n(x + width / 2)}" y="{_n(y + 14)}" font-family="{MONO}" font-size="10" '
            f'letter-spacing="0.8" text-anchor="middle" fill="{text_fill}">{xml_escape(label)}</text>')


def _header(audit: dict[str, Any]) -> list[str]:
    meta = audit["audit"]
    right = WIDTH - MARGIN
    completeness = _pct(meta.get("completeness_percent"))
    return [
        _text(MARGIN, 52, audit.get("organization", "ORGANIZATION").upper(), size=13, fill=MUTED, family=MONO, spacing=3),
        _text(MARGIN, 88, "DEVOPS CONTROL CENTER", size=28, weight="700", spacing=1),
        _text(MARGIN, 114, "Organization health dashboard", size=15, fill=MUTED),
        _text(right, 44, "LAST AUDIT", size=11, fill=MUTED, family=MONO, anchor="end", spacing=1.5),
        _text(right, 64, meta["timestamp"], size=14, family=MONO, anchor="end"),
        _text(right, 88, f"run {meta['run_id']} · {meta['status']} · {completeness} complete",
              size=12, fill=MUTED, family=MONO, anchor="end"),
        f'<line x1="{MARGIN}" y1="{HEADER_HEIGHT}" x2="{WIDTH - MARGIN}" y2="{HEADER_HEIGHT}" stroke="{BORDER}"/>',
    ]


def _metric_cards(audit: dict[str, Any]) -> list[str]:
    disc, m = audit["discovery"], audit["metrics"]
    cards = [("DISCOVERED", disc["total_discovered"]), ("AUDITED", disc["audited"]), ("HEALTHY", m["healthy"]),
             ("WARNING", m["warning"]), ("FAILED", m["failed"]), ("NO CI", m["no_ci"]), ("UNKNOWN", m["unknown"])]
    gap = 12
    card_w = (WIDTH - 2 * MARGIN - gap * (len(cards) - 1)) / len(cards)
    parts = []
    for i, (label, value) in enumerate(cards):
        x = MARGIN + i * (card_w + gap)
        parts.append(f'<rect x="{_n(x)}" y="{METRICS_Y}" width="{_n(card_w)}" height="{METRICS_H}" rx="8" '
                     f'fill="{PANEL}" stroke="{BORDER}"/>')
        parts.append(_text(x + 16, METRICS_Y + 28, label, size=11, fill=MUTED, family=MONO, spacing=1.5))
        parts.append(_text(x + 16, METRICS_Y + 74, str(value), size=34, weight="700"))
    return parts


def _health_panel(audit: dict[str, Any]) -> list[str]:
    m = audit["metrics"]
    x, y, w, h = MARGIN, VIZ_Y, 380, VIZ_H
    parts = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{PANEL}" stroke="{BORDER}"/>',
             _text(x + 20, y + 28, "ORGANIZATION HEALTH", size=11, fill=MUTED, family=MONO, spacing=1.5),
             _text(x + 20, y + 92, _pct(m["health_percent"]), size=56, weight="700"),
             _text(x + 20, y + 114, "healthy share of applicable repositories", size=12, fill=MUTED)]
    total = sum(m.get(key, 0) for _, key, _ in SEGMENTS)
    bar_x, bar_y, bar_w = x + 20, y + 134, w - 40
    if total:
        cursor = float(bar_x)
        for _, key, color in SEGMENTS:
            count = m.get(key, 0)
            if not count:
                continue
            seg = bar_w * count / total
            parts.append(f'<rect x="{_n(cursor)}" y="{bar_y}" width="{_n(seg)}" height="14" fill="{color}"/>')
            cursor += seg
    else:
        parts.append(f'<rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="14" fill="{TRACK}"/>')
    for i, (label, key, color) in enumerate(SEGMENTS):
        col, row = i % 3, i // 3
        lx = bar_x + col * 115
        ly = bar_y + 36 + row * 22
        parts.append(f'<rect x="{lx}" y="{ly - 9}" width="8" height="8" fill="{color}"/>')
        parts.append(_text(lx + 14, ly, f"{label} {m.get(key, 0)}", size=11, fill=MUTED))
    return parts


def _signal_panel(audit: dict[str, Any]) -> list[str]:
    x, y, w, h = 440, VIZ_Y, WIDTH - MARGIN - 440, VIZ_H
    rows = [
        ("CI/CD success (latest default-branch run)", audit["ci_statistics"]["success_percent"]),
        ("Branch protection compliance", audit["branch_protection"]["compliance_percent"]),
        ("Security configuration coverage", audit["security_statistics"]["coverage_percent"]),
        ("Environment audit coverage", audit["environment_statistics"]["coverage_percent"]),
        ("Audit completeness", audit["completeness"]["percent"]),
    ]
    parts = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{PANEL}" stroke="{BORDER}"/>',
             _text(x + 24, y + 28, "CONTROL SIGNALS", size=11, fill=MUTED, family=MONO, spacing=1.5)]
    track_x, track_w = x + 300, 300
    for i, (label, value) in enumerate(rows):
        ry = y + 62 + i * 36
        parts.append(_text(x + 24, ry + 4, label, size=13))
        parts.append(f'<rect x="{track_x}" y="{ry - 4}" width="{track_w}" height="8" rx="4" fill="{TRACK}"/>')
        if value is not None:
            parts.append(f'<rect x="{track_x}" y="{ry - 4}" width="{_n(track_w * max(0, min(value, 100)) / 100)}" '
                         f'height="8" rx="4" fill="#f0f0f0"/>')
        parts.append(_text(x + w - 24, ry + 4, _pct(value), size=13, weight="600", anchor="end"))
    return parts


def _repo_table(audit: dict[str, Any], row_limit: int) -> tuple[list[str], int]:
    repos = sorted(audit.get("repositories", []), key=lambda r: (OVERALL_ORDER.get(r["overall"], 9), r["name"].lower()))
    shown = repos[: max(row_limit, 0)]
    remaining = len(repos) - len(shown)
    rows_h = max(len(shown), 1) * ROW_HEIGHT
    height = 76 + rows_h + (30 if remaining else 0) + 18
    x, w = MARGIN, WIDTH - 2 * MARGIN
    parts = [f'<rect x="{x}" y="{TABLE_Y}" width="{w}" height="{height}" rx="8" fill="{PANEL}" stroke="{BORDER}"/>',
             _text(60, TABLE_Y + 34, "REPOSITORY STATUS", size=11, fill=MUTED, family=MONO, spacing=1.5),
             _text(WIDTH - 60, TABLE_Y + 34, f"showing {len(shown)} of {len(repos)}", size=12, fill=MUTED,
                   family=MONO, anchor="end")]
    heads = [(60, "REPOSITORY"), (380, "CI/CD"), (520, "SECURITY"), (680, "BRANCH"), (860, "ENVIRONMENT"), (1000, "OVERALL")]
    for hx, label in heads:
        parts.append(_text(hx, TABLE_Y + 58, label, size=10, fill=MUTED, family=MONO, spacing=1))
    parts.append(f'<line x1="60" y1="{TABLE_Y + 68}" x2="{WIDTH - 60}" y2="{TABLE_Y + 68}" stroke="{BORDER}"/>')
    if not shown:
        parts.append(_text(60, TABLE_Y + 96, "No repositories were audited in this run.", size=12, fill=MUTED))
    for i, repo in enumerate(shown):
        top = TABLE_Y + 76 + i * ROW_HEIGHT
        parts.append(_text(60, top + 17, truncate(repo["name"], 44), size=12, family=MONO))
        parts.append(_badge(380, top + 3, repo["ci"]["status"]))
        parts.append(_badge(520, top + 3, repo["security"]["status"]))
        parts.append(_badge(680, top + 3, repo["branch"]["status"]))
        parts.append(_badge(860, top + 3, repo["environment"]["status"]))
        parts.append(_badge(1000, top + 3, repo["overall"]))
        parts.append(f'<line x1="60" y1="{top + ROW_HEIGHT}" x2="{WIDTH - 60}" y2="{top + ROW_HEIGHT}" stroke="#1c1c1c"/>')
    if remaining:
        bottom = TABLE_Y + 76 + len(shown) * ROW_HEIGHT
        parts.append(_text(60, bottom + 20, f"+ {remaining} more repositories; the full list is in reports/organization-health.csv",
                           size=12, fill=MUTED))
    return parts, height


def _issues_panel(audit: dict[str, Any], top: int) -> tuple[list[str], int]:
    issues = audit.get("recent_issues", [])[:8]
    height = 52 + max(len(issues), 1) * 22 + 18
    x, w = MARGIN, WIDTH - 2 * MARGIN
    parts = [f'<rect x="{x}" y="{top}" width="{w}" height="{height}" rx="8" fill="{PANEL}" stroke="{BORDER}"/>',
             _text(60, top + 34, "RECENT ISSUES", size=11, fill=MUTED, family=MONO, spacing=1.5)]
    if not issues:
        parts.append(_text(60, top + 62, "No issues recorded in this audit.", size=12, fill=MUTED))
    for i, issue in enumerate(issues):
        line = (f"{issue['severity']}  {truncate(issue['repository'], 30)}  ·  {issue['area']}  ·  "
                f"{truncate(issue['message'], 110)}")
        parts.append(_text(60, top + 60 + i * 22, line, size=12, family=MONO))
    return parts, height


def _footer(audit: dict[str, Any], top: int) -> tuple[list[str], int]:
    meta = audit["audit"]
    repo_url = f"https://github.com/{audit['organization']}/{audit.get('control_repository', 'DevOps-Control-Center')}"
    parts = [
        f'<line x1="{MARGIN}" y1="{top - 8}" x2="{WIDTH - MARGIN}" y2="{top - 8}" stroke="{BORDER}"/>',
        _text(MARGIN, top + 18, "Automatically generated by DevOps-Control-Center.", size=12, fill=MUTED),
        _text(MARGIN, top + 40, f"Last successful audit: {meta['timestamp']} · run {meta['run_id']} · "
                                f"API limitations recorded: {len(audit.get('api_limitations', []))}",
              size=12, fill=MUTED, family=MONO),
        _text(MARGIN, top + 60, f"Central repository: {repo_url}", size=12, fill=MUTED, family=MONO),
    ]
    return parts, 74


def render_svg(audit: dict[str, Any], row_limit: int = 40) -> str:
    m, disc = audit["metrics"], audit["discovery"]
    body: list[str] = []
    body += _header(audit)
    body += _metric_cards(audit)
    body += _health_panel(audit)
    body += _signal_panel(audit)
    table_parts, table_h = _repo_table(audit, row_limit)
    body += table_parts
    issues_top = TABLE_Y + table_h + 18
    issue_parts, issues_h = _issues_panel(audit, issues_top)
    body += issue_parts
    footer_top = issues_top + issues_h + 22
    footer_parts, footer_h = _footer(audit, footer_top)
    body += footer_parts
    height = footer_top + footer_h + 8

    title = f"DevOps Control Center: {audit.get('organization', '')} organization health"
    desc = (f"{m['healthy']} of {m['applicable']} applicable repositories healthy ({_pct(m['health_percent'])}). "
            f"{m['failed']} failed, {m['warning']} with warnings, {m['no_ci']} without CI/CD, "
            f"{m['unknown']} unknown, out of {disc['audited']} audited.")
    head = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}" width="100%" '
        f'role="img" aria-labelledby="dcc-title dcc-desc" preserveAspectRatio="xMidYMid meet">',
        f'<title id="dcc-title">{xml_escape(title)}</title>',
        f'<desc id="dcc-desc">{xml_escape(desc)}</desc>',
        f'<rect x="0" y="0" width="{WIDTH}" height="{height}" fill="{BG}"/>',
    ]
    return "\n".join(head + body + ["</svg>"]) + "\n"
