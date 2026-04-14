from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from PIL import ExifTags, Image, UnidentifiedImageError
from scipy.signal import find_peaks

TIMESTAMP_OFFSET_SECONDS = 76
PEAK_MIN_HEIGHT_PPM = 2.150
PEAK_PROMINENCE_PPM = 0.05
PEAK_DISTANCE_POINTS = 1
IMAGE_NAME_PATTERN = re.compile(
    r"^(?P<image_id>\d+)_(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{2}-\d{2}-\d{2})$"
)
EXIF_TIMESTAMP_KEYS = ("DateTimeOriginal", "DateTimeDigitized", "DateTime")
MATCHABLE_TIMESTAMP_SOURCES = {
    "filename_timestamp",
    "exif_datetime_original",
    "exif_datetime_digitized",
    "exif_datetime",
}


def _to_local_timestamp(epoch_seconds: float | None) -> pd.Timestamp:
    if epoch_seconds is None:
        return pd.NaT
    return pd.Timestamp(datetime.fromtimestamp(epoch_seconds)).replace(microsecond=0)


def _parse_exif_timestamp(value: Any) -> pd.Timestamp:
    if value in (None, ""):
        return pd.NaT
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    return pd.to_datetime(str(value).strip(), format="%Y:%m:%d %H:%M:%S", errors="coerce")


def extract_image_metadata(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    stat_result = path.stat()

    metadata: dict[str, Any] = {
        "filesystem_created_datetime": _to_local_timestamp(getattr(stat_result, "st_birthtime", None)),
        "filesystem_modified_datetime": _to_local_timestamp(stat_result.st_mtime),
        "exif_datetime_original": pd.NaT,
        "exif_datetime_digitized": pd.NaT,
        "exif_datetime": pd.NaT,
        "metadata_timestamp": pd.NaT,
        "metadata_timestamp_source": "none",
    }

    try:
        with Image.open(path) as image:
            exif = image.getexif()
    except (UnidentifiedImageError, OSError):
        exif = None

    if exif:
        exif_by_name = {ExifTags.TAGS.get(key, key): value for key, value in exif.items()}
        metadata["exif_datetime_original"] = _parse_exif_timestamp(exif_by_name.get("DateTimeOriginal"))
        metadata["exif_datetime_digitized"] = _parse_exif_timestamp(exif_by_name.get("DateTimeDigitized"))
        metadata["exif_datetime"] = _parse_exif_timestamp(exif_by_name.get("DateTime"))

        for field_name, source_name in (
            ("exif_datetime_original", "exif_datetime_original"),
            ("exif_datetime_digitized", "exif_datetime_digitized"),
            ("exif_datetime", "exif_datetime"),
        ):
            if pd.notna(metadata[field_name]):
                metadata["metadata_timestamp"] = metadata[field_name]
                metadata["metadata_timestamp_source"] = source_name
                break

    return metadata


def slugify_output_prefix(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "methane"


def load_gas_data(csv_path: str | Path, offset_seconds: int = TIMESTAMP_OFFSET_SECONDS) -> pd.DataFrame:
    csv_path = Path(csv_path)
    df = pd.read_csv(csv_path, encoding="cp1252")
    df.columns = df.columns.str.strip()

    required_cols = ["DATAH", "SECONDS", "DATE", "TIME", "CH4"]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")

    df = df[df["DATAH"].astype(str).str.strip() == "DATA"].copy()
    df["SECONDS"] = pd.to_numeric(df["SECONDS"], errors="coerce")
    df["CH4"] = pd.to_numeric(df["CH4"], errors="coerce")
    df["Datetime"] = pd.to_datetime(
        df["DATE"].astype(str).str.strip() + " " + df["TIME"].astype(str).str.strip(),
        format="%m/%d/%Y %H:%M:%S",
        errors="coerce",
    )
    df = df.dropna(subset=["SECONDS", "Datetime", "CH4"]).copy()
    df = df.sort_values("SECONDS").reset_index(drop=True)

    df["CH4_ppm"] = df["CH4"] / 1000.0
    df["Elapsed_sec"] = df["SECONDS"] - df["SECONDS"].iloc[0]
    df["Corrected_Datetime"] = df["Datetime"] + pd.to_timedelta(offset_seconds, unit="s")

    return df


def load_image_data(image_dir: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    image_dir = Path(image_dir)
    parsed_rows: list[dict[str, Any]] = []
    unparsed_rows: list[dict[str, Any]] = []

    for path in sorted(image_dir.iterdir()):
        if not path.is_file():
            continue

        match = IMAGE_NAME_PATTERN.match(path.stem)
        metadata = extract_image_metadata(path)
        image_row = {
            "image_id": pd.NA,
            "image_file": path.name,
            "image_extension": path.suffix.lower(),
            "image_datetime": pd.NaT,
            "image_path": str(path.resolve()),
            "image_timestamp_source": "unresolved",
            "timestamp_confidence": "unresolved",
            **metadata,
        }

        if match:
            image_row["image_id"] = int(match.group("image_id"))
            image_row["image_datetime"] = pd.to_datetime(
                f"{match.group('date')} {match.group('time').replace('-', ':')}",
                format="%Y-%m-%d %H:%M:%S",
            )
            image_row["image_timestamp_source"] = "filename_timestamp"
            image_row["timestamp_confidence"] = "high"
            parsed_rows.append(image_row)
            continue

        if metadata["metadata_timestamp_source"] in MATCHABLE_TIMESTAMP_SOURCES:
            image_row["image_datetime"] = metadata["metadata_timestamp"]
            image_row["image_timestamp_source"] = metadata["metadata_timestamp_source"]
            image_row["timestamp_confidence"] = "medium"
            parsed_rows.append(image_row)
            continue

        image_row["reason"] = "filename_did_not_match_expected_pattern_and_no_embedded_timestamp"
        unparsed_rows.append(image_row)

    images_df = pd.DataFrame(parsed_rows).sort_values(["image_datetime", "image_file"]).reset_index(drop=True)
    unparsed_df = pd.DataFrame(unparsed_rows)
    return images_df, unparsed_df


def find_duplicate_image_timestamps(images_df: pd.DataFrame) -> pd.DataFrame:
    if images_df.empty:
        return pd.DataFrame(columns=["image_datetime", "image_count", "image_files"])

    duplicate_counts = (
        images_df.groupby("image_datetime")
        .size()
        .rename("image_count")
        .reset_index()
    )
    duplicate_counts = duplicate_counts[duplicate_counts["image_count"] > 1].copy()
    if duplicate_counts.empty:
        return pd.DataFrame(columns=["image_datetime", "image_count", "image_files"])

    duplicate_files = (
        images_df.groupby("image_datetime")["image_file"]
        .apply(lambda files: " | ".join(sorted(files)))
        .rename("image_files")
        .reset_index()
    )
    return duplicate_counts.merge(duplicate_files, on="image_datetime", how="left")


def build_image_match_table(
    gas_df: pd.DataFrame,
    images_df: pd.DataFrame,
    tolerance_seconds: int = 1,
) -> pd.DataFrame:
    if images_df.empty:
        return pd.DataFrame(
            columns=[
                "image_id",
                "image_file",
                "image_extension",
                "image_datetime",
                "image_path",
                "image_timestamp_source",
                "timestamp_confidence",
                "metadata_timestamp",
                "metadata_timestamp_source",
                "filesystem_created_datetime",
                "filesystem_modified_datetime",
                "exif_datetime_original",
                "exif_datetime_digitized",
                "exif_datetime",
                "SECONDS",
                "Elapsed_sec",
                "Datetime",
                "Corrected_Datetime",
                "CH4",
                "CH4_ppm",
                "delta_seconds",
                "exact_timestamp_match",
                "match_status",
                "within_corrected_data_window",
            ]
        )

    gas_sorted = gas_df.sort_values("Corrected_Datetime").copy()
    images_sorted = images_df.sort_values("image_datetime").copy()

    matched = pd.merge_asof(
        images_sorted,
        gas_sorted,
        left_on="image_datetime",
        right_on="Corrected_Datetime",
        direction="nearest",
        tolerance=pd.Timedelta(seconds=tolerance_seconds),
    )

    matched["delta_seconds"] = (
        matched["image_datetime"] - matched["Corrected_Datetime"]
    ).dt.total_seconds()
    matched["exact_timestamp_match"] = matched["delta_seconds"].eq(0)
    matched["match_status"] = matched["Corrected_Datetime"].notna().map(
        {True: "matched", False: "no_match_within_tolerance"}
    )

    corrected_start = gas_df["Corrected_Datetime"].min()
    corrected_end = gas_df["Corrected_Datetime"].max()
    matched["within_corrected_data_window"] = matched["image_datetime"].between(corrected_start, corrected_end)

    return matched


def build_peak_photo_summary(
    gas_df: pd.DataFrame,
    images_df: pd.DataFrame,
    peak_min_height_ppm: float = PEAK_MIN_HEIGHT_PPM,
    peak_prominence_ppm: float = PEAK_PROMINENCE_PPM,
    peak_distance_points: int = PEAK_DISTANCE_POINTS,
) -> pd.DataFrame:
    peak_indices, peak_properties = find_peaks(
        gas_df["CH4_ppm"].values,
        height=peak_min_height_ppm,
        prominence=peak_prominence_ppm,
        distance=peak_distance_points,
    )

    peak_df = gas_df.iloc[peak_indices][
        ["SECONDS", "Elapsed_sec", "Datetime", "Corrected_Datetime", "CH4", "CH4_ppm"]
    ].copy()
    if peak_df.empty:
        return pd.DataFrame(
            columns=[
                "peak_rank_by_ch4",
                "SECONDS",
                "Elapsed_sec",
                "Datetime",
                "Corrected_Datetime",
                "CH4",
                "CH4_ppm",
                "peak_prominence_ppm",
                "peak_height_ppm",
                "peak_over_100ppm",
                "nearest_image_id",
                "nearest_image_file",
                "nearest_image_datetime",
                "nearest_image_timestamp_source",
                "nearest_image_path",
                "nearest_image_delta_seconds",
                "nearest_image_abs_delta_seconds",
                "nearest_image_relation",
            ]
        )

    peak_df["peak_prominence_ppm"] = peak_properties["prominences"]
    peak_df["peak_height_ppm"] = peak_properties["peak_heights"]
    peak_df["peak_over_100ppm"] = peak_df["CH4_ppm"] >= 100
    peak_df = peak_df.sort_values("CH4_ppm", ascending=False).reset_index(drop=True)
    peak_df["peak_rank_by_ch4"] = range(1, len(peak_df) + 1)

    if images_df.empty:
        peak_df["nearest_image_id"] = pd.NA
        peak_df["nearest_image_file"] = pd.NA
        peak_df["nearest_image_datetime"] = pd.NaT
        peak_df["nearest_image_timestamp_source"] = pd.NA
        peak_df["nearest_image_path"] = pd.NA
        peak_df["nearest_image_delta_seconds"] = pd.NA
        peak_df["nearest_image_abs_delta_seconds"] = pd.NA
        peak_df["nearest_image_relation"] = pd.NA
        return peak_df

    image_lookup = (
        images_df[
            [
                "image_id",
                "image_file",
                "image_datetime",
                "image_timestamp_source",
                "image_path",
            ]
        ]
        .sort_values("image_datetime")
        .rename(
            columns={
                "image_id": "nearest_image_id",
                "image_file": "nearest_image_file",
                "image_datetime": "nearest_image_datetime",
                "image_timestamp_source": "nearest_image_timestamp_source",
                "image_path": "nearest_image_path",
            }
        )
    )
    peak_df = peak_df.sort_values("Corrected_Datetime").reset_index(drop=True)
    peak_df = pd.merge_asof(
        peak_df,
        image_lookup,
        left_on="Corrected_Datetime",
        right_on="nearest_image_datetime",
        direction="nearest",
    )
    peak_df["nearest_image_delta_seconds"] = (
        peak_df["nearest_image_datetime"] - peak_df["Corrected_Datetime"]
    ).dt.total_seconds()
    peak_df["nearest_image_abs_delta_seconds"] = peak_df["nearest_image_delta_seconds"].abs()
    peak_df["nearest_image_relation"] = peak_df["nearest_image_delta_seconds"].map(
        lambda delta: "exact" if delta == 0 else ("after" if delta > 0 else "before")
    )
    return peak_df.sort_values("peak_rank_by_ch4").reset_index(drop=True)


def build_combined_event_report(
    overlap_matches_df: pd.DataFrame,
    peak_photo_summary_df: pd.DataFrame,
) -> pd.DataFrame:
    matched_image_events = overlap_matches_df[overlap_matches_df["match_status"] == "matched"].copy()
    matched_image_events = matched_image_events[
        [
            "Corrected_Datetime",
            "Elapsed_sec",
            "CH4_ppm",
            "image_id",
            "image_file",
            "image_datetime",
            "image_timestamp_source",
            "image_path",
            "delta_seconds",
        ]
    ].rename(
        columns={
            "Elapsed_sec": "matched_elapsed_sec",
            "CH4_ppm": "matched_ch4_ppm",
            "image_id": "matched_image_id",
            "image_file": "matched_image_file",
            "image_datetime": "matched_image_datetime",
            "image_timestamp_source": "matched_image_timestamp_source",
            "image_path": "matched_image_path",
            "delta_seconds": "matched_image_delta_seconds",
        }
    )

    peak_events = peak_photo_summary_df[
        [
            "Corrected_Datetime",
            "Elapsed_sec",
            "CH4_ppm",
            "peak_rank_by_ch4",
            "peak_prominence_ppm",
            "peak_height_ppm",
            "peak_over_100ppm",
            "nearest_image_id",
            "nearest_image_file",
            "nearest_image_datetime",
            "nearest_image_timestamp_source",
            "nearest_image_path",
            "nearest_image_delta_seconds",
            "nearest_image_abs_delta_seconds",
            "nearest_image_relation",
        ]
    ].rename(
        columns={
            "Elapsed_sec": "peak_elapsed_sec",
            "CH4_ppm": "peak_ch4_ppm",
        }
    )

    combined = pd.merge(
        matched_image_events,
        peak_events,
        on="Corrected_Datetime",
        how="outer",
    )
    combined["event_elapsed_sec"] = combined["matched_elapsed_sec"].combine_first(combined["peak_elapsed_sec"])
    combined["event_ch4_ppm"] = combined["matched_ch4_ppm"].combine_first(combined["peak_ch4_ppm"])
    combined["has_exact_image_match"] = combined["matched_image_file"].notna()
    combined["is_detected_peak"] = combined["peak_rank_by_ch4"].notna()
    combined["report_row_type"] = "unclassified"
    combined.loc[
        combined["has_exact_image_match"] & combined["is_detected_peak"],
        "report_row_type",
    ] = "matched_image_and_peak"
    combined.loc[
        combined["has_exact_image_match"] & ~combined["is_detected_peak"],
        "report_row_type",
    ] = "matched_image_only"
    combined.loc[
        ~combined["has_exact_image_match"] & combined["is_detected_peak"],
        "report_row_type",
    ] = "peak_only"

    combined["best_image_file"] = combined["matched_image_file"].combine_first(combined["nearest_image_file"])
    combined["best_image_datetime"] = combined["matched_image_datetime"].combine_first(
        combined["nearest_image_datetime"]
    )
    combined["best_image_path"] = combined["matched_image_path"].combine_first(combined["nearest_image_path"])
    combined["best_image_delta_seconds"] = combined["matched_image_delta_seconds"].where(
        combined["matched_image_file"].notna(),
        combined["nearest_image_delta_seconds"],
    )
    combined["best_image_link_type"] = "no_image"
    combined.loc[combined["matched_image_file"].notna(), "best_image_link_type"] = "exact_image_match"
    combined.loc[
        combined["matched_image_file"].isna() & combined["nearest_image_file"].notna(),
        "best_image_link_type",
    ] = "nearest_peak_image"

    combined = combined.sort_values(
        ["Corrected_Datetime", "peak_rank_by_ch4", "matched_image_file"],
        na_position="last",
    ).reset_index(drop=True)
    return combined


def build_summary(
    gas_df: pd.DataFrame,
    images_df: pd.DataFrame,
    all_matches_df: pd.DataFrame,
    overlap_matches_df: pd.DataFrame,
    peak_photo_summary_df: pd.DataFrame,
    combined_event_report_df: pd.DataFrame,
    duplicate_image_times_df: pd.DataFrame,
    unparsed_images_df: pd.DataFrame,
    offset_seconds: int = TIMESTAMP_OFFSET_SECONDS,
) -> dict[str, Any]:
    matched_overlap = overlap_matches_df[overlap_matches_df["match_status"] == "matched"]
    unmatched_overlap = overlap_matches_df[overlap_matches_df["match_status"] != "matched"]

    return {
        "offset_seconds": offset_seconds,
        "gas_rows": int(len(gas_df)),
        "gas_raw_start": gas_df["Datetime"].min(),
        "gas_raw_end": gas_df["Datetime"].max(),
        "gas_corrected_start": gas_df["Corrected_Datetime"].min(),
        "gas_corrected_end": gas_df["Corrected_Datetime"].max(),
        "parsed_images": int(len(images_df)),
        "filename_timestamp_images": int(images_df["image_timestamp_source"].eq("filename_timestamp").sum()),
        "metadata_timestamp_images": int(images_df["image_timestamp_source"].ne("filename_timestamp").sum()),
        "images_in_corrected_window": int(len(overlap_matches_df)),
        "matched_images_in_corrected_window": int(len(matched_overlap)),
        "unmatched_images_in_corrected_window": int(len(unmatched_overlap)),
        "exact_matches_in_corrected_window": int(matched_overlap["exact_timestamp_match"].sum()),
        "images_outside_corrected_window": int((~all_matches_df["within_corrected_data_window"]).sum()),
        "detected_peaks": int(len(peak_photo_summary_df)),
        "peaks_over_100ppm": int(peak_photo_summary_df["peak_over_100ppm"].sum()),
        "combined_report_rows": int(len(combined_event_report_df)),
        "duplicate_image_timestamps": int(len(duplicate_image_times_df)),
        "unparsed_images": int(len(unparsed_images_df)),
    }


def write_outputs(
    output_dir: str | Path,
    all_matches_df: pd.DataFrame,
    overlap_matches_df: pd.DataFrame,
    peak_photo_summary_df: pd.DataFrame,
    combined_event_report_df: pd.DataFrame,
    duplicate_image_times_df: pd.DataFrame,
    unparsed_images_df: pd.DataFrame,
    output_prefix: str,
) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_prefix = slugify_output_prefix(output_prefix)

    output_paths = {
        "all_matches_csv": output_dir / f"{output_prefix}_all_image_matches.csv",
        "overlap_matches_csv": output_dir / f"{output_prefix}_overlap_image_matches.csv",
        "peak_photo_summary_csv": output_dir / f"{output_prefix}_peak_photo_summary.csv",
        "combined_event_report_csv": output_dir / f"{output_prefix}_combined_event_report.csv",
        "duplicate_image_timestamps_csv": output_dir / f"{output_prefix}_duplicate_image_timestamps.csv",
        "unparsed_images_csv": output_dir / f"{output_prefix}_unparsed_images.csv",
    }

    all_matches_df.to_csv(output_paths["all_matches_csv"], index=False)
    overlap_matches_df.to_csv(output_paths["overlap_matches_csv"], index=False)
    peak_photo_summary_df.to_csv(output_paths["peak_photo_summary_csv"], index=False)
    combined_event_report_df.to_csv(output_paths["combined_event_report_csv"], index=False)
    duplicate_image_times_df.to_csv(output_paths["duplicate_image_timestamps_csv"], index=False)
    unparsed_images_df.to_csv(output_paths["unparsed_images_csv"], index=False)

    return output_paths


def run_matching_workflow(
    csv_path: str | Path,
    image_dir: str | Path,
    output_dir: str | Path | None = None,
    offset_seconds: int = TIMESTAMP_OFFSET_SECONDS,
    tolerance_seconds: int = 1,
    output_prefix: str | None = None,
) -> dict[str, Any]:
    csv_path = Path(csv_path)
    image_dir = Path(image_dir)
    gas_df = load_gas_data(csv_path, offset_seconds=offset_seconds)
    images_df, unparsed_images_df = load_image_data(image_dir)
    duplicate_image_times_df = find_duplicate_image_timestamps(images_df)
    all_matches_df = build_image_match_table(gas_df, images_df, tolerance_seconds=tolerance_seconds)
    overlap_matches_df = all_matches_df[all_matches_df["within_corrected_data_window"]].copy()
    peak_photo_summary_df = build_peak_photo_summary(gas_df, images_df)
    combined_event_report_df = build_combined_event_report(overlap_matches_df, peak_photo_summary_df)

    summary = build_summary(
        gas_df=gas_df,
        images_df=images_df,
        all_matches_df=all_matches_df,
        overlap_matches_df=overlap_matches_df,
        peak_photo_summary_df=peak_photo_summary_df,
        combined_event_report_df=combined_event_report_df,
        duplicate_image_times_df=duplicate_image_times_df,
        unparsed_images_df=unparsed_images_df,
        offset_seconds=offset_seconds,
    )

    output_paths: dict[str, Path] = {}
    if output_dir is not None:
        output_paths = write_outputs(
            output_dir=output_dir,
            all_matches_df=all_matches_df,
            overlap_matches_df=overlap_matches_df,
            peak_photo_summary_df=peak_photo_summary_df,
            combined_event_report_df=combined_event_report_df,
            duplicate_image_times_df=duplicate_image_times_df,
            unparsed_images_df=unparsed_images_df,
            output_prefix=output_prefix or csv_path.stem,
        )

    return {
        "gas_df": gas_df,
        "images_df": images_df,
        "all_matches_df": all_matches_df,
        "overlap_matches_df": overlap_matches_df,
        "peak_photo_summary_df": peak_photo_summary_df,
        "combined_event_report_df": combined_event_report_df,
        "duplicate_image_times_df": duplicate_image_times_df,
        "unparsed_images_df": unparsed_images_df,
        "summary": summary,
        "output_paths": output_paths,
    }


def build_arg_parser(
    default_csv_path: str | Path | None = None,
    default_images_dir: str | Path | None = None,
    default_output_dir: str | Path | None = None,
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Match methane measurements to field images by timestamp."
    )
    parser.add_argument(
        "--csv-path",
        default=str(default_csv_path) if default_csv_path is not None else None,
        required=default_csv_path is None,
        help="Path to the methane CSV file.",
    )
    parser.add_argument(
        "--image-dir",
        default=str(default_images_dir) if default_images_dir is not None else None,
        required=default_images_dir is None,
        help="Directory containing field images.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(default_output_dir) if default_output_dir is not None else None,
        required=default_output_dir is None,
        help="Directory where output CSV files should be written.",
    )
    parser.add_argument(
        "--offset-seconds",
        type=int,
        default=TIMESTAMP_OFFSET_SECONDS,
        help="Number of seconds to add to the methane instrument timestamp.",
    )
    parser.add_argument(
        "--tolerance-seconds",
        type=int,
        default=1,
        help="Nearest-match tolerance in seconds for image-to-data joins.",
    )
    parser.add_argument(
        "--output-prefix",
        default=None,
        help="Optional prefix for output filenames. Defaults to the CSV stem.",
    )
    return parser


def cli_main(
    default_csv_path: str | Path | None = None,
    default_images_dir: str | Path | None = None,
    default_output_dir: str | Path | None = None,
) -> dict[str, Any]:
    parser = build_arg_parser(
        default_csv_path=default_csv_path,
        default_images_dir=default_images_dir,
        default_output_dir=default_output_dir,
    )
    args = parser.parse_args()

    results = run_matching_workflow(
        csv_path=args.csv_path,
        image_dir=args.image_dir,
        output_dir=args.output_dir,
        offset_seconds=args.offset_seconds,
        tolerance_seconds=args.tolerance_seconds,
        output_prefix=args.output_prefix,
    )

    print("Methane image-matching summary")
    for key, value in results["summary"].items():
        print(f"{key}: {value}")

    print("Output files:")
    for name, path in results["output_paths"].items():
        print(f"{name}: {path}")
    return results


if __name__ == "__main__":
    cli_main()
