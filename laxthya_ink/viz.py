"""Pen-path preview: draw the pen-down polylines on the paper area and save a PNG.

matplotlib is imported lazily and with the non-interactive Agg backend, so this
works on a machine without a display.
"""

from __future__ import annotations

from pathlib import Path

Pt = tuple[float, float]


def render_preview(segments: list[list[Pt]], config: dict, out_path: str | Path, title: str = "") -> Path:
    """Save `segments` (pen-tip polylines, bed mm) over the paper rectangle; return the path."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    paper, machine = config["paper"], config["machine"]
    fig, ax = plt.subplots(figsize=(6, 6 * machine["y_max"] / machine["x_max"]))
    ax.add_patch(Rectangle(
        (paper["origin_x"], paper["origin_y"]), paper["width_mm"], paper["height_mm"],
        fill=False, edgecolor="0.6", linestyle="--", linewidth=1,
    ))
    for poly in segments:
        xs, ys = zip(*poly)
        if len(poly) == 1:
            ax.plot(xs, ys, marker="o", markersize=2, color="black")   # a dot
        else:
            ax.plot(xs, ys, color="black", linewidth=1)
    ax.set_xlim(0, machine["x_max"])
    ax.set_ylim(0, machine["y_max"])
    ax.set_aspect("equal")
    ax.set_xlabel("bed X (mm)")
    ax.set_ylabel("bed Y (mm)")
    if title:
        ax.set_title(title)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out
