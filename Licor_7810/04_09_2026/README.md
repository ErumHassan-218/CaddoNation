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
- `well16_report_figures.py`: generates report-ready methane figures for Well16
- `../../methane_image_matching.py`: repo-level reusable CLI for other wells and dates
- `requirements.txt`: Python packages used by the workflow
- `Well 16/graph.ipynb`: plotting notebook
- `outputs/well16_all_image_matches.csv`: all parsed images with match status
- `outputs/well16_overlap_image_matches.csv`: images inside the corrected methane time window
- `outputs/well16_peak_photo_summary.csv`: detected methane peaks with the nearest field image
- `outputs/well16_combined_event_report.csv`: one table that combines event rows, peak flags, and the best linked image

## Report Figures

Run this from the `Methane_Data` repo root:

```bash
python3 Licor_7810/04_09_2026/well16_report_figures.py
```

This creates:

- `outputs/report_figures/well16_report_overall_signal.png`: overall methane signal for the field visit
- `outputs/report_figures/well16_report_section_overview.png`: four time-based sections for clearer signal review
- `outputs/report_figures/well16_report_peak_with_photo.png`: the highest methane peak paired with the nearest field image

## Notes

- The photo files are intentionally not stored in this repo folder.
- The workflow expects image filenames in the form `ID_YYYY-MM-DD_HH-MM-SS.ext`.
- If a filename does not include a timestamp, the workflow will try embedded EXIF time fields before leaving the image in the QA output.
- The current photo folder used by the workflow is `Wells/W16/Field Visit Data/Field Pictures`.
