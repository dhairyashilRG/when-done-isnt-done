"""Draw figures/summary.svg from the result files. Standard library only.

Run from the repository root:  .venv/bin/python figures/make_summary_figure.py
"""
import csv
import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "repro" / "results"
OUT = Path(__file__).resolve().parent / "summary.svg"

SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#e4e3df"
BLUE, ORANGE = "#2a78d6", "#eb6834"   # validated pair (light surface)
FONT = "font-family='-apple-system, Segoe UI, Helvetica, Arial, sans-serif'"

W, H = 1200, 720
PW, PH = 560, 330            # panel size
PANELS = [(30, 110), (610, 110), (30, 450), (610, 450)]


def text(x, y, s, size=14, fill=INK, anchor="start", weight="normal"):
    return (f"<text x='{x}' y='{y}' {FONT} font-size='{size}' fill='{fill}' "
            f"text-anchor='{anchor}' font-weight='{weight}'>{escape(s)}</text>")


def panel_head(x, y, title, verdict):
    return [text(x, y + 20, title, 17, INK, weight="600"),
            text(x, y + 42, verdict, 13, INK2)]


def bars(x, y, rows, unit="%"):
    """Horizontal bars, 0-100, one series. rows: [(label, value)]."""
    out, lab_w, plot_w, top, step = [], 230, 270, y + 80, 52
    x0 = x + lab_w
    for t in (0, 50, 100):
        gx = x0 + plot_w * t / 100
        out.append(f"<line x1='{gx}' y1='{top - 14}' x2='{gx}' y2='{top + step * len(rows) - 18}' "
                   f"stroke='{GRID}' stroke-width='1'/>")
        out.append(text(gx, top + step * len(rows) - 2, f"{t}{unit}", 12, MUTED, "middle"))
    for i, (label, v) in enumerate(rows):
        cy = top + i * step
        out.append(text(x0 - 12, cy + 5, label, 14, INK2, "end"))
        w = max(plot_w * v / 100, 0)
        if w > 0:
            out.append(f"<rect x='{x0}' y='{cy - 11}' width='{w:.1f}' height='22' rx='4' fill='{BLUE}'/>")
        else:
            out.append(f"<line x1='{x0}' y1='{cy - 11}' x2='{x0}' y2='{cy + 11}' stroke='{BLUE}' stroke-width='3'/>")
        out.append(text(x0 + w + 8, cy + 5, f"{v:.0f}{unit}", 14, INK, weight="600"))
    return out


def dumbbell(x, y, runs):
    """Per run: rules claimed done vs rules the hidden tests confirmed (axis 20-32)."""
    out, lab_w, plot_w, top, step, lo, hi = [], 70, 400, y + 92, 36, 20, 32
    x0 = x + lab_w
    sx = lambda v: x0 + plot_w * (v - lo) / (hi - lo)  # noqa: E731
    # legend (two series), above the plot
    out += [f"<circle cx='{x + 8}' cy='{y + 64}' r='6' fill='{ORANGE}'/>", text(x + 20, y + 69, "claimed done", 13, INK2),
            f"<circle cx='{x + 128}' cy='{y + 64}' r='6' fill='{BLUE}'/>",
            text(x + 140, y + 69, "confirmed by hidden tests", 13, INK2)]
    for t in (20, 25, 30, 32):
        gx = sx(t)
        out.append(f"<line x1='{gx}' y1='{top - 14}' x2='{gx}' y2='{top + step * len(runs) - 18}' "
                   f"stroke='{GRID}' stroke-width='1'/>")
        out.append(text(gx, top + step * len(runs) - 2, str(t), 12, MUTED, "middle"))
    for i, (run, claimed, confirmed) in enumerate(runs):
        cy = top + i * step
        out.append(text(x0 - 12, cy + 5, run, 14, INK2, "end"))
        out.append(f"<line x1='{sx(claimed)}' y1='{cy}' x2='{sx(confirmed)}' y2='{cy}' stroke='{GRID}' stroke-width='4'/>")
        out.append(f"<circle cx='{sx(claimed)}' cy='{cy}' r='7' fill='{ORANGE}' stroke='{SURFACE}' stroke-width='2'/>")
        out.append(f"<circle cx='{sx(confirmed)}' cy='{cy}' r='7' fill='{BLUE}' stroke='{SURFACE}' stroke-width='2'/>")
        out.append(text(sx(claimed) - 12, cy + 5, str(claimed), 13, INK2, "end"))
        out.append(text(sx(confirmed) + 12, cy + 5, str(confirmed), 13, INK2))
    return out


def main():
    v = json.loads((RESULTS / "verdicts.json").read_text())
    with open(RESULTS / "e1_done.csv") as f:
        runs = [(f"run {i + 1}", int(r["ticked"]), int(r["heldout_pass"])) for i, r in enumerate(csv.DictReader(f))]
    e2, e3, e4 = v["E2"]["rates"], v["E3"], v["E4"]
    parts = [f"<svg xmlns='http://www.w3.org/2000/svg' width='{W}' height='{H}' viewBox='0 0 {W} {H}'>",
             f"<rect width='{W}' height='{H}' fill='{SURFACE}'/>",
             text(30, 46, "Four patterns from a private agent-built system, retested on a 32-rule toy spec", 22, INK, weight="700"),
             text(30, 76, f"Claude Sonnet 5.5, {v['E1b']['n']} runs. Pass/fail rules fixed in advance; "
                          "every number replays offline from the saved responses.", 15, INK2)]
    (ax, ay), (bx, by), (cx, cy), (dx, dy) = PANELS
    parts += panel_head(ax, ay, "1. Did “done” overstate what worked?", "No: the agent claimed less than it built (not reproduced)")
    parts += dumbbell(ax, ay, runs)
    parts += panel_head(bx, by, "2. Checks that pass on empty input", "Common at first; one written rule removed it (not reproduced)")
    parts += bars(bx, by, [("no instruction", 100 * v["E2"]["base_V1_V9"]),
                           ("written rule, same step", 100 * e2["checklist/V1-V6"]),
                           ("written rule, later step", 100 * e2["checklist/V7-V9"]),
                           ("guard built into checks", 100 * e2["guard/V1-V6"])])
    parts += panel_head(cx, cy, "3. Second version agrees with the first", "Same-conversation copy always agreed (partly reproduced)")
    parts += bars(cx, cy, [("same conversation", 100 * (1 - e3["disagreement_impl_R_dep"])),
                           ("fresh conversation", 100 * (1 - e3["disagreement_impl_R_ind"]))])
    parts.append(text(cx, cy + 210, "share of 20 random test sequences on which it matched the main version", 13, MUTED))
    parts += panel_head(dx, dy, "4. Agent asked the owner at a reserved decision", "It asked more often when the gate was only written (not reproduced)")
    parts += bars(dx, dy, [("enforced by code", 100 * e4["stopped_code"]),
                           ("written only", 100 * e4["stopped_prose"])])
    parts.append(text(W - 30, H - 16, "Source: repro/results/verdicts.json, e1_done.csv", 12, MUTED, "end"))
    parts.append("</svg>")
    OUT.write_text("\n".join(parts) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
