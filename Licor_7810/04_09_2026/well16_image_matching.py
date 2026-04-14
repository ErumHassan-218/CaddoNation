from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from methane_image_matching import (  # noqa: F401
    IMAGE_NAME_PATTERN,
    MATCHABLE_TIMESTAMP_SOURCES,
    PEAK_DISTANCE_POINTS,
    PEAK_MIN_HEIGHT_PPM,
    PEAK_PROMINENCE_PPM,
    TIMESTAMP_OFFSET_SECONDS,
    build_arg_parser,
    build_image_match_table,
    build_peak_photo_summary,
    build_summary,
    cli_main,
    extract_image_metadata,
    find_duplicate_image_timestamps,
    load_gas_data,
    load_image_data,
    run_matching_workflow,
    slugify_output_prefix,
    write_outputs,
)


def main() -> None:
    project_root = Path(__file__).resolve().parent
    default_csv_path = project_root / "Well16.csv"
    default_images_dir = project_root.parents[2] / "Wells" / "W16" / "Field Visit Data" / "Field Pictures"
    default_output_dir = project_root / "outputs"
    cli_main(
        default_csv_path=default_csv_path,
        default_images_dir=default_images_dir,
        default_output_dir=default_output_dir,
    )


if __name__ == "__main__":
    main()
