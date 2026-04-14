# Well16 Timestamp Matching

This folder now contains a small, GitHub-friendly workflow for matching Well16 methane readings to field images by timestamp.

For reusable runs across other wells and dates, use the repo-root CLI in [README.md](/Users/erumhassan/Library/CloudStorage/OneDrive-UniversityofOklahoma/Caddo%20Nation%20Field%20Survey%20-%20Documents/Methane_Data/README.md).

## What It Does

- Loads `Well16.csv`
- Applies a `+76 second` correction to the instrument timestamp
- Parses image filenames from the W16 field photo folder
- Falls back to embedded EXIF timestamps when an image filename does not include a timestamp
- Matches each image to the nearest corrected methane row within a 1-second tolerance
- Writes CSV outputs to `outputs/`

## Main Files

- `well16_image_matching.py`: reusable matching logic
- `requirements.txt`: Python packages used by the workflow
- `Excel/graph.ipynb`: plotting notebook
- `outputs/well16_all_image_matches.csv`: all parsed images with match status
- `outputs/well16_overlap_image_matches.csv`: images inside the corrected methane time window
- `outputs/well16_peak_photo_summary.csv`: detected methane peaks with the nearest field image

## Notes

- The photo files are intentionally not stored in this repo folder.
- The workflow expects image filenames in the form `ID_YYYY-MM-DD_HH-MM-SS.ext`.
- If a filename does not include a timestamp, the workflow will try embedded EXIF time fields before leaving the image in the QA output.
- The current photo folder used by the workflow is `Wells/W16/Field Visit Data/Field Pictures`.
