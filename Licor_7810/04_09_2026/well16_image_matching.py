from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from PIL import ExifTags, Image, UnidentifiedImageError

TIMESTAMP_OFFSET_SECONDS = 76
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


def build_summary(
    gas_df: pd.DataFrame,
    images_df: pd.DataFrame,
    all_matches_df: pd.DataFrame,
    overlap_matches_df: pd.DataFrame,
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
        "duplicate_image_timestamps": int(len(duplicate_image_times_df)),
        "unparsed_images": int(len(unparsed_images_df)),
    }


def write_outputs(
    output_dir: str | Path,
    all_matches_df: pd.DataFrame,
    overlap_matches_df: pd.DataFrame,
    duplicate_image_times_df: pd.DataFrame,
    unparsed_images_df: pd.DataFrame,
) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_paths = {
        "all_matches_csv": output_dir / "well16_all_image_matches.csv",
        "overlap_matches_csv": output_dir / "well16_overlap_image_matches.csv",
        "duplicate_image_timestamps_csv": output_dir / "well16_duplicate_image_timestamps.csv",
        "unparsed_images_csv": output_dir / "well16_unparsed_images.csv",
    }

    all_matches_df.to_csv(output_paths["all_matches_csv"], index=False)
    overlap_matches_df.to_csv(output_paths["overlap_matches_csv"], index=False)
    duplicate_image_times_df.to_csv(output_paths["duplicate_image_timestamps_csv"], index=False)
    unparsed_images_df.to_csv(output_paths["unparsed_images_csv"], index=False)

    return output_paths


def run_matching_workflow(
    csv_path: str | Path,
    image_dir: str | Path,
    output_dir: str | Path | None = None,
    offset_seconds: int = TIMESTAMP_OFFSET_SECONDS,
    tolerance_seconds: int = 1,
) -> dict[str, Any]:
    gas_df = load_gas_data(csv_path, offset_seconds=offset_seconds)
    images_df, unparsed_images_df = load_image_data(image_dir)
    duplicate_image_times_df = find_duplicate_image_timestamps(images_df)
    all_matches_df = build_image_match_table(gas_df, images_df, tolerance_seconds=tolerance_seconds)
    overlap_matches_df = all_matches_df[all_matches_df["within_corrected_data_window"]].copy()

    summary = build_summary(
        gas_df=gas_df,
        images_df=images_df,
        all_matches_df=all_matches_df,
        overlap_matches_df=overlap_matches_df,
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
            duplicate_image_times_df=duplicate_image_times_df,
            unparsed_images_df=unparsed_images_df,
        )

    return {
        "gas_df": gas_df,
        "images_df": images_df,
        "all_matches_df": all_matches_df,
        "overlap_matches_df": overlap_matches_df,
        "duplicate_image_times_df": duplicate_image_times_df,
        "unparsed_images_df": unparsed_images_df,
        "summary": summary,
        "output_paths": output_paths,
    }


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent
    default_csv_path = project_root / "Well16.csv"
    default_images_dir = project_root.parents[2] / "Wells" / "W16" / "Field Visit Data" / "Field Pictures"
    default_output_dir = project_root / "outputs"

    results = run_matching_workflow(
        csv_path=default_csv_path,
        image_dir=default_images_dir,
        output_dir=default_output_dir,
    )

    print("Well16 image-matching summary")
    for key, value in results["summary"].items():
        print(f"{key}: {value}")

    print("Output files:")
    for name, path in results["output_paths"].items():
        print(f"{name}: {path}")
