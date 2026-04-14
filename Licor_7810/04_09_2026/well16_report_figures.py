from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PROJECT_ROOT.parents[1]
DOCUMENTS_ROOT = PROJECT_ROOT.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from methane_image_matching import TIMESTAMP_OFFSET_SECONDS, run_matching_workflow

SECTION_COUNT = 4
REPORT_DPI = 300
SIGNIFICANT_PEAK_MIN_PPM = 3.0


def load_report_image(image_path: str | Path) -> Image.Image:
    image_path = Path(image_path)
    suffix = image_path.suffix.lower()
    if suffix in {".heic", ".heif"}:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            temp_path = Path(tmp.name)
        try:
            subprocess.run(
                ["sips", "-s", "format", "png", str(image_path), "--out", str(temp_path)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            with Image.open(temp_path) as image:
                return image.convert("RGB")
        finally:
            temp_path.unlink(missing_ok=True)

    with Image.open(image_path) as image:
        return image.convert("RGB")


def setup_report_style() -> None:
    plt.rcParams.update(
        {
            "font.size": 11,
            "axes.titlesize": 14,
            "axes.labelsize": 11,
            "axes.linewidth": 1.0,
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )


def build_section_edges(df: pd.DataFrame, section_count: int = SECTION_COUNT) -> pd.DatetimeIndex:
    start = df["Corrected_Datetime"].min()
    end = df["Corrected_Datetime"].max()
    return pd.date_range(start=start, end=end, periods=section_count + 1)


def make_overall_signal_figure(
    df: pd.DataFrame,
    overlap_matches_df: pd.DataFrame,
    peak_photo_summary_df: pd.DataFrame,
    output_path: Path,
) -> None:
    setup_report_style()
    fig, ax = plt.subplots(figsize=(13.5, 6.2))

    ax.plot(
        df["Corrected_Datetime"],
        df["CH4_ppm"],
        color="#1F4E79",
        linewidth=1.8,
        label="CH$_4$ signal",
    )

    exact_matches = overlap_matches_df[overlap_matches_df["match_status"] == "matched"].copy()
    ax.scatter(
        exact_matches["Corrected_Datetime"],
        exact_matches["CH4_ppm"],
        s=28,
        marker="v",
        color="#2F2F2F",
        alpha=0.75,
        label="Image timestamps",
        zorder=4,
    )

    high_peaks = peak_photo_summary_df[peak_photo_summary_df["peak_over_100ppm"]].copy()
    ax.scatter(
        high_peaks["Corrected_Datetime"],
        high_peaks["CH4_ppm"],
        s=65,
        color="#C44E52",
        edgecolor="white",
        linewidth=0.8,
        label="Peaks > 100 ppm",
        zorder=5,
    )

    for _, row in high_peaks.iterrows():
        ax.annotate(
            f"P{int(row['peak_rank_by_ch4'])}",
            (row["Corrected_Datetime"], row["CH4_ppm"]),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
            fontsize=9,
            color="#7A1E24",
            weight="bold",
        )

    ax.axhline(100, color="#B22222", linestyle="--", linewidth=1.3, label="100 ppm threshold")

    section_edges = build_section_edges(df)
    section_labels = ["A", "B", "C", "D"]
    for idx, label in enumerate(section_labels):
        left = section_edges[idx]
        right = section_edges[idx + 1]
        if idx % 2 == 0:
            ax.axvspan(left, right, color="#EAF1F7", alpha=0.42, zorder=0)
        x_mid = left + (right - left) / 2
        ax.text(
            x_mid,
            1.015,
            f"Section {label}",
            transform=ax.get_xaxis_transform(),
            ha="center",
            va="bottom",
            fontsize=9,
            color="#4B4B4B",
        )

    ax.set_title("Well 16 Methane Signal Overview")
    ax.set_xlabel("Corrected Time")
    ax.set_ylabel("CH$_4$ (ppm)")
    ax.set_ylim(0, df["CH4_ppm"].max() * 1.06)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    fig.autofmt_xdate(rotation=20)
    ax.grid(True, linestyle="--", alpha=0.25)
    ax.legend(frameon=False, loc="upper right")

    ax.text(
        0.01,
        0.99,
        "Instrument timestamps corrected by +76 s",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=9,
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=0.2),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output_path, dpi=REPORT_DPI, bbox_inches="tight")
    plt.close(fig)


def make_section_overview_figure(
    df: pd.DataFrame,
    overlap_matches_df: pd.DataFrame,
    peak_photo_summary_df: pd.DataFrame,
    output_path: Path,
) -> None:
    setup_report_style()
    section_edges = build_section_edges(df)
    significant_peaks = peak_photo_summary_df[peak_photo_summary_df["CH4_ppm"] >= SIGNIFICANT_PEAK_MIN_PPM].copy()
    matched_images = overlap_matches_df[overlap_matches_df["match_status"] == "matched"].copy()

    fig, axes = plt.subplots(SECTION_COUNT, 1, figsize=(13.5, 12.5))
    section_labels = ["A", "B", "C", "D"]

    for idx, ax in enumerate(axes):
        left = section_edges[idx]
        right = section_edges[idx + 1]
        mask = (df["Corrected_Datetime"] >= left) & (
            df["Corrected_Datetime"] <= right if idx == SECTION_COUNT - 1 else df["Corrected_Datetime"] < right
        )
        section_df = df[mask].copy()
        section_images = matched_images[
            (matched_images["Corrected_Datetime"] >= left)
            & (matched_images["Corrected_Datetime"] <= right if idx == SECTION_COUNT - 1 else matched_images["Corrected_Datetime"] < right)
        ].copy()
        section_peaks = significant_peaks[
            (significant_peaks["Corrected_Datetime"] >= left)
            & (significant_peaks["Corrected_Datetime"] <= right if idx == SECTION_COUNT - 1 else significant_peaks["Corrected_Datetime"] < right)
        ].copy()

        ax.plot(
            section_df["Corrected_Datetime"],
            section_df["CH4_ppm"],
            color="#1F4E79",
            linewidth=1.6,
        )
        if not section_images.empty:
            ax.scatter(
                section_images["Corrected_Datetime"],
                section_images["CH4_ppm"],
                s=26,
                marker="v",
                color="#2F2F2F",
                alpha=0.75,
                zorder=4,
            )
        if not section_peaks.empty:
            ax.scatter(
                section_peaks["Corrected_Datetime"],
                section_peaks["CH4_ppm"],
                s=38,
                color="#C44E52",
                edgecolor="white",
                linewidth=0.8,
                zorder=5,
            )

        local_max = section_df["CH4_ppm"].max()
        y_max = max(local_max * 1.08, 3.0)
        if local_max >= 20:
            y_max = max(y_max, 110)
            ax.axhline(100, color="#B22222", linestyle="--", linewidth=1.0, alpha=0.9)
        ax.set_ylim(0, y_max)

        if not section_peaks.empty:
            top_peak = section_peaks.sort_values("CH4_ppm", ascending=False).iloc[0]
            ax.text(
                0.99,
                0.92,
                f"Local peak: {top_peak['CH4_ppm']:.2f} ppm at {pd.to_datetime(top_peak['Corrected_Datetime']).strftime('%H:%M:%S')}",
                transform=ax.transAxes,
                ha="right",
                va="top",
                fontsize=9,
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=0.2),
            )

        ax.set_ylabel("CH$_4$ (ppm)")
        ax.grid(True, linestyle="--", alpha=0.25)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        ax.set_title(
            f"Section {section_labels[idx]} | {left.strftime('%H:%M:%S')}–{right.strftime('%H:%M:%S')}",
            loc="left",
        )

    axes[-1].set_xlabel("Corrected Time")
    fig.suptitle("Well 16 Methane Signal by Sequential Sections", y=0.995, fontsize=15)
    fig.autofmt_xdate(rotation=20)
    fig.tight_layout(rect=(0, 0, 1, 0.985))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=REPORT_DPI, bbox_inches="tight")
    plt.close(fig)


def make_peak_with_photo_figure(
    df: pd.DataFrame,
    peak_photo_summary_df: pd.DataFrame,
    output_path: Path,
) -> None:
    setup_report_style()
    if peak_photo_summary_df.empty:
        raise ValueError("No detected methane peaks were available for the report figure.")

    peak_row = peak_photo_summary_df.sort_values("peak_rank_by_ch4").iloc[0]
    if pd.isna(peak_row.get("nearest_image_path")) or pd.isna(peak_row.get("nearest_image_datetime")):
        raise ValueError("The highest-ranked methane peak does not have a linked field image.")

    peak_time = pd.to_datetime(peak_row["Corrected_Datetime"])
    image_time = pd.to_datetime(peak_row["nearest_image_datetime"])
    image_path = Path(peak_row["nearest_image_path"])
    image = load_report_image(image_path)

    window_start = min(peak_time - pd.Timedelta(seconds=90), image_time - pd.Timedelta(seconds=20))
    window_end = max(peak_time + pd.Timedelta(seconds=90), image_time + pd.Timedelta(seconds=20))
    window_df = df[(df["Corrected_Datetime"] >= window_start) & (df["Corrected_Datetime"] <= window_end)].copy()

    fig = plt.figure(figsize=(13.5, 6.8))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.45, 1.0])
    ax_plot = fig.add_subplot(gs[0, 0])
    ax_img = fig.add_subplot(gs[0, 1])

    ax_plot.plot(
        window_df["Corrected_Datetime"],
        window_df["CH4_ppm"],
        color="#1F4E79",
        linewidth=1.8,
    )
    ax_plot.scatter(
        [peak_time],
        [peak_row["CH4_ppm"]],
        s=95,
        color="#C44E52",
        edgecolor="white",
        linewidth=0.9,
        zorder=5,
        label="Highest peak",
    )
    ax_plot.axvline(peak_time, color="#C44E52", linewidth=1.2, linestyle="-")
    ax_plot.axvline(
        image_time,
        color="#2F2F2F",
        linewidth=1.2,
        linestyle="--",
        label="Nearest field image",
    )
    ax_plot.set_title("Primary Methane Peak and Nearest Field Photo", loc="left")
    ax_plot.set_xlabel("Corrected Time")
    ax_plot.set_ylabel("CH$_4$ (ppm)")
    ax_plot.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    ax_plot.grid(True, linestyle="--", alpha=0.25)
    ax_plot.legend(frameon=False, loc="upper right")

    info_text = (
        f"Peak: {peak_row['CH4_ppm']:.2f} ppm at {peak_time.strftime('%H:%M:%S')}\n"
        f"Nearest image: {image_path.name}\n"
        f"Image time: {image_time.strftime('%H:%M:%S')} ({peak_row['nearest_image_relation']} by "
        f"{abs(float(peak_row['nearest_image_delta_seconds'])):.0f} s)"
    )
    ax_plot.text(
        0.02,
        0.98,
        info_text,
        transform=ax_plot.transAxes,
        ha="left",
        va="top",
        fontsize=9,
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.88, pad=0.3),
    )

    ax_img.imshow(image)
    ax_img.set_title(f"Field image: {image_path.name}", fontsize=12)
    ax_img.axis("off")
    ax_img.text(
        0.5,
        -0.06,
        "Nearest available image to the highest detected methane peak",
        transform=ax_img.transAxes,
        ha="center",
        va="top",
        fontsize=9,
    )

    fig.autofmt_xdate(rotation=20)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=REPORT_DPI, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    csv_file = PROJECT_ROOT / "Well16.csv"
    images_dir = DOCUMENTS_ROOT / "Wells" / "W16" / "Field Visit Data" / "Field Pictures"
    output_dir = PROJECT_ROOT / "outputs"
    report_dir = output_dir / "report_figures"

    results = run_matching_workflow(
        csv_path=csv_file,
        image_dir=images_dir,
        output_dir=output_dir,
        offset_seconds=TIMESTAMP_OFFSET_SECONDS,
        tolerance_seconds=1,
        output_prefix="well16",
    )

    df = results["gas_df"]
    overlap_matches_df = results["overlap_matches_df"]
    peak_photo_summary_df = results["peak_photo_summary_df"]

    overall_path = report_dir / "well16_report_overall_signal.png"
    section_path = report_dir / "well16_report_section_overview.png"
    peak_path = report_dir / "well16_report_peak_with_photo.png"

    make_overall_signal_figure(df, overlap_matches_df, peak_photo_summary_df, overall_path)
    make_section_overview_figure(df, overlap_matches_df, peak_photo_summary_df, section_path)
    make_peak_with_photo_figure(df, peak_photo_summary_df, peak_path)

    print("Report-ready figures")
    print(f"overall_signal: {overall_path}")
    print(f"section_overview: {section_path}")
    print(f"peak_with_photo: {peak_path}")


if __name__ == "__main__":
    main()
