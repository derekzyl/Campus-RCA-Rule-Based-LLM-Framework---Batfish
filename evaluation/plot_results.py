#!/usr/bin/env python3
"""Generate dissertation-ready tables and charts from evaluation_report.json."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MODE_ORDER = ["rule_only", "llm_only", "hybrid"]


def load_report(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "summary" not in data or "rows" not in data:
        raise ValueError(f"{path} must contain 'summary' and 'rows'")
    return data


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    fields = [
        "scenario_id",
        "mode",
        "truth_fault",
        "truth_device",
        "predicted_fault",
        "predicted_device",
        "localisation_correct",
        "keyword_coverage",
        "hallucination_rate",
        "evidence_faithfulness",
        "elapsed_ms",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_summary_csv(summary: dict[str, Any], path: Path) -> None:
    fields = [
        "mode",
        "n",
        "accuracy",
        "avg_keyword_coverage",
        "avg_hallucination_rate",
        "avg_evidence_faithfulness",
        "avg_elapsed_ms",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for mode in MODE_ORDER:
            if mode not in summary:
                continue
            row = {"mode": mode, **summary[mode]}
            w.writerow(row)


def write_latex_tables(summary: dict[str, Any], rows: list[dict[str, Any]], path: Path) -> None:
    lines = [
        "% Auto-generated from evaluation_report.json — paste into Chapter 5",
        "",
        "% --- Aggregate metrics ---",
        r"\begin{table}[ht]",
        r"\centering",
        r"\caption{Aggregate localisation and explanation metrics by mode}",
        r"\label{tab:rca-aggregate}",
        r"\begin{tabular}{lrrrrr}",
        r"\toprule",
        r"Mode & Accuracy & Keyword cov. & Hallucination & Faithfulness & Avg.\ ms \\",
        r"\midrule",
    ]
    for mode in MODE_ORDER:
        if mode not in summary:
            continue
        s = summary[mode]
        lines.append(
            f"{mode.replace('_', r'\_')} & {s['accuracy']:.2f} & "
            f"{s['avg_keyword_coverage']:.3f} & {s['avg_hallucination_rate']:.2f} & "
            f"{s['avg_evidence_faithfulness']:.2f} & {s['avg_elapsed_ms']:.1f} \\\\"
        )
    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            r"\end{table}",
            "",
            "% --- Per-scenario localisation matrix ---",
            r"\begin{table}[ht]",
            r"\centering",
            r"\caption{Per-scenario localisation outcomes (OK/MISS)}",
            r"\label{tab:rca-per-scenario}",
            r"\begin{tabular}{l" + "c" * len([m for m in MODE_ORDER if m in {r['mode'] for r in rows}]) + "}",
            r"\toprule",
        ]
    )
    modes_present = [m for m in MODE_ORDER if any(r["mode"] == m for r in rows)]
    lines.append("Scenario & " + " & ".join(m.replace("_", r"\_") for m in modes_present) + r" \\")
    lines.append(r"\midrule")

    scenarios: list[str] = []
    for r in rows:
        if r["scenario_id"] not in scenarios:
            scenarios.append(r["scenario_id"])
    lookup = {(r["scenario_id"], r["mode"]): r for r in rows}
    for sid in scenarios:
        cells = []
        for mode in modes_present:
            r = lookup.get((sid, mode))
            if not r:
                cells.append("--")
            else:
                cells.append("OK" if r["localisation_correct"] else "MISS")
        lines.append(sid.replace("_", r"\_") + " & " + " & ".join(cells) + r" \\")
    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            r"\end{table}",
            "",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _mode_labels(modes: list[str]) -> list[str]:
    # Avoid multiline labels: WSL + high Windows DPI can trigger FreeType raster overflow.
    return [m.replace("_", " ") for m in modes]


def _running_on_wsl_or_mnt_c() -> bool:
    import os
    import platform

    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        if "microsoft" in platform.release().lower():
            return True
    except Exception:  # noqa: BLE001
        pass
    # Project / cwd on Windows drive mounted into WSL
    try:
        cwd = str(Path.cwd().resolve())
        if cwd.startswith("/mnt/c/") or cwd.startswith("/mnt/C/"):
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _configure_matplotlib(*, safe: bool = False) -> None:
    """Force a WSL-safe Agg/font setup before creating figures."""
    import os

    # Keep matplotlib cache on the Linux filesystem (not /mnt/c).
    cache_dir = Path.home() / ".cache" / "campus-rca-mpl"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(cache_dir)
    os.environ["MPLBACKEND"] = "Agg"
    # Windows DPI forwarding into WSL often inflates glyph bitmaps past FreeType limits.
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"
    os.environ["GDK_SCALE"] = "1"
    os.environ["GDK_DPI_SCALE"] = "1"

    import matplotlib

    matplotlib.use("Agg", force=True)
    from matplotlib import font_manager, rcParams

    # Prefer the TTF matplotlib ships with — never Windows fonts from /mnt/c/Windows/Fonts.
    bundled = Path(matplotlib.__file__).resolve().parent / "mpl-data" / "fonts" / "ttf" / "DejaVuSans.ttf"
    system = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    font_path = bundled if bundled.exists() else system
    if font_path.exists():
        try:
            font_manager.fontManager.addfont(str(font_path))
        except Exception:  # noqa: BLE001
            pass
        font_name = font_manager.FontProperties(fname=str(font_path)).get_name()
        rcParams["font.family"] = "sans-serif"
        rcParams["font.sans-serif"] = [font_name, "DejaVu Sans"]
    else:
        rcParams["font.family"] = "sans-serif"
        rcParams["font.sans-serif"] = ["DejaVu Sans", "sans-serif"]

    rcParams.update(
        {
            "figure.dpi": 80 if safe else 100,
            "savefig.dpi": 100 if safe else 120,
            "font.size": 8 if safe else 9,
            "axes.titlesize": 10 if safe else 11,
            "axes.labelsize": 9 if safe else 10,
            "xtick.labelsize": 8 if safe else 9,
            "ytick.labelsize": 8 if safe else 9,
            "legend.fontsize": 8 if safe else 9,
            "axes.unicode_minus": False,
            "text.usetex": False,
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
        }
    )


def _savefig(fig, path: Path, dpi: int) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor="white")


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _pillow_font(size: int = 14):
    """Load a font without relying on broken WSL FreeType paths when possible."""
    from PIL import ImageFont

    candidates = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    try:
        import matplotlib

        bundled = (
            Path(matplotlib.__file__).resolve().parent
            / "mpl-data"
            / "fonts"
            / "ttf"
            / "DejaVuSans.ttf"
        )
        candidates.insert(0, bundled)
    except Exception:  # noqa: BLE001
        pass

    for path in candidates:
        if path.exists():
            try:
                # Small sizes avoid FreeType raster overflow even with TTF.
                return ImageFont.truetype(str(path), size=max(10, min(size, 18)))
            except Exception:  # noqa: BLE001
                continue
    return ImageFont.load_default()


def _draw_text(draw, xy, text: str, fill=(20, 20, 20), size: int = 14) -> None:
    font = _pillow_font(size)
    draw.text(xy, text, fill=fill, font=font)


def _plot_charts_pillow(
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
    out_dir: Path,
) -> list[Path]:
    """
    FreeType-free-ish chart renderer for WSL.

    Uses Pillow pixel drawing. Prefer bitmap/default fonts if TTF load fails.
    """
    from PIL import Image, ImageDraw

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    modes = [m for m in MODE_ORDER if m in summary]
    if not modes:
        return written

    colors = ["#2F6F4E", "#B85C38", "#1F4E79"]
    labels = _mode_labels(modes)

    def save_bar(
        path: Path,
        title: str,
        values: list[float],
        ylabel: str,
        ymax: float | None = None,
        value_fmt: str = "{:.2f}",
    ) -> None:
        w, h = 900, 520
        img = Image.new("RGB", (w, h), "white")
        draw = ImageDraw.Draw(img)
        left, right, top, bottom = 90, 40, 60, 80
        plot_w = w - left - right
        plot_h = h - top - bottom
        _draw_text(draw, (left, 18), title, size=16)
        _draw_text(draw, (12, top + plot_h // 2), ylabel, size=12)

        vmax = ymax if ymax is not None else max(values + [1.0])
        if vmax <= 0:
            vmax = 1.0
        n = len(values)
        gap = 30
        bar_w = max(40, (plot_w - gap * (n + 1)) // max(n, 1))
        # axes
        draw.line((left, top, left, top + plot_h), fill=(80, 80, 80), width=2)
        draw.line((left, top + plot_h, left + plot_w, top + plot_h), fill=(80, 80, 80), width=2)
        for i, (lab, val, col) in enumerate(zip(labels, values, colors)):
            x0 = left + gap + i * (bar_w + gap)
            bar_h = int((val / vmax) * (plot_h - 10))
            y0 = top + plot_h - bar_h
            draw.rectangle([x0, y0, x0 + bar_w, top + plot_h], fill=_hex_to_rgb(col))
            _draw_text(draw, (x0, top + plot_h + 12), lab, size=12)
            _draw_text(draw, (x0 + 4, max(top + 4, y0 - 22)), value_fmt.format(val), size=12)
        img.save(path)
        written.append(path)

    # 1) Accuracy
    save_bar(
        out_dir / "fig_accuracy_by_mode.png",
        "Localisation accuracy by diagnosis mode",
        [float(summary[m]["accuracy"]) for m in modes],
        "Accuracy",
        ymax=1.15,
        value_fmt="{:.0%}",
    )

    # 2) Grouped metrics as separate small multiples in one image
    metric_defs = [
        ("accuracy", "Accuracy"),
        ("avg_keyword_coverage", "Keyword"),
        ("avg_evidence_faithfulness", "Faithful"),
        ("avg_hallucination_rate", "Halluc."),
    ]
    w, h = 1000, 560
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)
    _draw_text(draw, (30, 18), "Explanation-quality metrics by mode", size=16)
    group_w = (w - 60) // len(metric_defs)
    for gi, (key, lab) in enumerate(metric_defs):
        gx = 30 + gi * group_w
        gy = 70
        gw, gh = group_w - 20, 400
        draw.rectangle([gx, gy, gx + gw, gy + gh], outline=(180, 180, 180), width=1)
        _draw_text(draw, (gx + 8, gy + 8), lab, size=13)
        vals = [float(summary[m][key]) for m in modes]
        bar_w = max(18, (gw - 40) // (len(modes) * 2))
        for i, (val, col) in enumerate(zip(vals, colors)):
            bh = int(val * (gh - 80))
            x0 = gx + 20 + i * (bar_w + 18)
            y0 = gy + gh - 30 - bh
            draw.rectangle([x0, y0, x0 + bar_w, gy + gh - 30], fill=_hex_to_rgb(col))
            _draw_text(draw, (x0 - 4, gy + gh - 24), modes[i][:4], size=11)
            _draw_text(draw, (x0 - 2, max(gy + 28, y0 - 18)), f"{val:.2f}", size=11)
    # legend
    lx = 30
    for i, mode in enumerate(modes):
        draw.rectangle([lx, h - 40, lx + 16, h - 24], fill=_hex_to_rgb(colors[i]))
        _draw_text(draw, (lx + 22, h - 42), mode, size=12)
        lx += 180
    p = out_dir / "fig_metrics_by_mode.png"
    img.save(p)
    written.append(p)

    # 3) Localisation matrix
    scenarios: list[str] = []
    for r in rows:
        if r["scenario_id"] not in scenarios:
            scenarios.append(r["scenario_id"])
    lookup = {(r["scenario_id"], r["mode"]): r for r in rows}
    cell_w, cell_h = 140, 50
    left, top = 260, 70
    w = left + cell_w * len(modes) + 40
    h = top + cell_h * len(scenarios) + 60
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)
    _draw_text(draw, (20, 18), "Per-scenario localisation (green=OK, red=MISS)", size=15)
    for j, mode in enumerate(modes):
        _draw_text(draw, (left + j * cell_w + 10, top - 28), mode, size=12)
    for i, sid in enumerate(scenarios):
        _draw_text(draw, (12, top + i * cell_h + 14), sid, size=12)
        for j, mode in enumerate(modes):
            r = lookup.get((sid, mode))
            ok = bool(r and r["localisation_correct"])
            color = (47, 158, 90) if ok else (196, 70, 70)
            if r is None:
                color = (200, 200, 200)
            x0 = left + j * cell_w
            y0 = top + i * cell_h
            draw.rectangle([x0, y0, x0 + cell_w - 8, y0 + cell_h - 8], fill=color)
            label = "--" if r is None else ("OK" if ok else "MISS")
            _draw_text(draw, (x0 + 45, y0 + 12), label, fill=(255, 255, 255), size=14)
    p = out_dir / "fig_localisation_matrix.png"
    img.save(p)
    written.append(p)

    # 4) Latency
    save_bar(
        out_dir / "fig_latency_by_mode.png",
        "Average diagnosis latency by mode",
        [float(summary[m]["avg_elapsed_ms"]) for m in modes],
        "ms",
        ymax=None,
        value_fmt="{:.0f}",
    )
    return written


def _plot_charts_once(
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
    out_dir: Path,
    *,
    dpi: int,
) -> list[Path]:
    import matplotlib.pyplot as plt
    import numpy as np

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    modes = [m for m in MODE_ORDER if m in summary]
    if not modes:
        return written

    colors = ["#2F6F4E", "#B85C38", "#1F4E79"]

    # 1) Accuracy bar chart
    fig, ax = plt.subplots(figsize=(6.5, 3.8))
    acc = [summary[m]["accuracy"] for m in modes]
    bars = ax.bar(_mode_labels(modes), acc, color=colors[: len(modes)], width=0.55)
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("Localisation accuracy")
    ax.set_title("Localisation accuracy by diagnosis mode")
    ax.axhline(1.0, color="#888888", linestyle="--", linewidth=0.8)
    for bar, v in zip(bars, acc):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            v + 0.03,
            f"{v:.0%}",
            ha="center",
            fontsize=8,
        )
    p = out_dir / "fig_accuracy_by_mode.png"
    _savefig(fig, p, dpi)
    plt.close(fig)
    written.append(p)

    # 2) Grouped metrics
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    metrics = [
        ("accuracy", "Accuracy"),
        ("avg_keyword_coverage", "Keyword cov."),
        ("avg_evidence_faithfulness", "Faithfulness"),
        ("avg_hallucination_rate", "Hallucination"),
    ]
    x = np.arange(len(metrics))
    width = 0.25
    for i, mode in enumerate(modes):
        vals = [summary[mode][k] for k, _ in metrics]
        ax.bar(x + (i - 1) * width, vals, width, label=mode, color=colors[i])
    ax.set_xticks(x)
    ax.set_xticklabels([lab for _, lab in metrics])
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("Score (0-1)")
    ax.set_title("Explanation-quality metrics by mode")
    ax.legend(frameon=False)
    p = out_dir / "fig_metrics_by_mode.png"
    _savefig(fig, p, dpi)
    plt.close(fig)
    written.append(p)

    # 3) Per-scenario OK/MISS matrix
    scenarios: list[str] = []
    for r in rows:
        if r["scenario_id"] not in scenarios:
            scenarios.append(r["scenario_id"])
    lookup = {(r["scenario_id"], r["mode"]): r for r in rows}
    matrix = np.full((len(scenarios), len(modes)), np.nan)
    for i, sid in enumerate(scenarios):
        for j, mode in enumerate(modes):
            r = lookup.get((sid, mode))
            if r is not None:
                matrix[i, j] = 1.0 if r["localisation_correct"] else 0.0

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    im = ax.imshow(matrix, cmap="RdYlGn", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(modes)))
    ax.set_xticklabels(modes, rotation=15, ha="right")
    ax.set_yticks(range(len(scenarios)))
    ax.set_yticklabels(scenarios)
    ax.set_title("Per-scenario localisation (green=OK, red=MISS)")
    for i in range(len(scenarios)):
        for j in range(len(modes)):
            if not np.isnan(matrix[i, j]):
                ax.text(
                    j,
                    i,
                    "OK" if matrix[i, j] == 1 else "MISS",
                    ha="center",
                    va="center",
                    fontsize=8,
                )
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    p = out_dir / "fig_localisation_matrix.png"
    _savefig(fig, p, dpi)
    plt.close(fig)
    written.append(p)

    # 4) Latency comparison
    fig, ax = plt.subplots(figsize=(6.5, 3.8))
    ms = [summary[m]["avg_elapsed_ms"] for m in modes]
    ax.bar(_mode_labels(modes), ms, color=colors[: len(modes)], width=0.55)
    ax.set_ylabel("Average elapsed time (ms)")
    ax.set_title("Average diagnosis latency by mode")
    for i, v in enumerate(ms):
        ax.text(i, v, f"{v:.0f}", ha="center", va="bottom", fontsize=8)
    p = out_dir / "fig_latency_by_mode.png"
    _savefig(fig, p, dpi)
    plt.close(fig)
    written.append(p)

    return written


def plot_charts(summary: dict[str, Any], rows: list[dict[str, Any]], out_dir: Path) -> list[Path]:
    """
    Render charts with WSL-safe defaults.

    On WSL (especially projects under /mnt/c), matplotlib/FreeType often hits
    raster overflow via Windows fonts. Prefer Pillow there; otherwise try
    matplotlib and fall back to Pillow on FreeType errors.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # Pillow path first on WSL /mnt/c — most reliable.
    if _running_on_wsl_or_mnt_c():
        return _plot_charts_pillow(summary, rows, out_dir)

    attempts = (
        {"safe": False, "dpi": 120},
        {"safe": True, "dpi": 90},
        {"safe": True, "dpi": 72},
    )
    last_err: Exception | None = None
    for attempt in attempts:
        try:
            _configure_matplotlib(safe=bool(attempt["safe"]))
            return _plot_charts_once(summary, rows, out_dir, dpi=int(attempt["dpi"]))
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            msg = str(exc).lower()
            if not any(
                tok in msg
                for tok in ("raster overflow", "ft2font", "freetype", "failed with error 0x62")
            ):
                # Unexpected error: still try Pillow before giving up.
                break
            try:
                import matplotlib.pyplot as plt

                plt.close("all")
            except Exception:  # noqa: BLE001
                pass

    # Final fallback: Pillow (no matplotlib text rendering).
    try:
        return _plot_charts_pillow(summary, rows, out_dir)
    except Exception as pillow_exc:  # noqa: BLE001
        raise RuntimeError(
            "Failed to render charts (matplotlib FreeType + Pillow fallback). "
            "CSV/LaTeX tables were still written. "
            "Copy the project to a Linux path (e.g. ~/sal) instead of /mnt/c/..., then retry."
        ) from (pillow_exc if last_err is None else last_err)


def export_all(report_path: Path, out_dir: Path | None = None) -> dict[str, Any]:
    data = load_report(report_path)
    out_dir = out_dir or report_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = data["summary"]
    rows = data["rows"]

    artifacts = {
        "csv_rows": out_dir / "evaluation_rows.csv",
        "csv_summary": out_dir / "evaluation_summary.csv",
        "latex": out_dir / "evaluation_tables.tex",
    }
    write_csv(rows, artifacts["csv_rows"])
    write_summary_csv(summary, artifacts["csv_summary"])
    write_latex_tables(summary, rows, artifacts["latex"])

    figures: list[Path] = []
    figure_error: str | None = None
    try:
        figures = plot_charts(summary, rows, out_dir / "figures")
    except Exception as exc:  # noqa: BLE001
        figure_error = str(exc)
        (out_dir / "figures_error.txt").write_text(figure_error + "\n", encoding="utf-8")

    return {
        "tables": artifacts,
        "figures": figures,
        "out_dir": out_dir,
        "figure_error": figure_error,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot tables/charts from RCA evaluation JSON")
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "results" / "evaluation_report.json",
        help="Path to evaluation_report.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory (default: same folder as report)",
    )
    args = parser.parse_args()
    if not args.report.exists():
        raise SystemExit(
            f"Missing {args.report}. Run evaluation first:\n"
            "  uv run python evaluation/run_eval.py --out results"
        )
    result = export_all(args.report, args.out)
    print(f"Wrote tables to {result['out_dir']}")
    for p in result["tables"].values():
        print(f"  - {p}")
    if result.get("figure_error"):
        print(f"Figures failed: {result['figure_error']}")
    else:
        print("Figures:")
        for p in result["figures"]:
            print(f"  - {p}")


if __name__ == "__main__":
    main()
