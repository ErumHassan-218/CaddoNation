# Methane Data Matching

This repo root now includes a reusable CLI for matching methane CSV timestamps to field images.

## What To Run

- For the reusable repo-level workflow, run `python3 methane_image_matching.py ...` from the `Methane_Data` repo root.
- For the current Well16 defaults only, run `python3 Licor_7810/04_09_2026/well16_image_matching.py`.
- For interactive review and plots, open `Licor_7810/04_09_2026/Excel/graph.ipynb` and run the cells from top to bottom.

## Generic CLI

Run from the `Methane_Data` repo root:

```bash
python3 methane_image_matching.py \
  --csv-path Licor_7810/04_09_2026/Well16.csv \
  --image-dir "../Wells/W16/Field Visit Data/Field Pictures" \
  --output-dir Licor_7810/04_09_2026/outputs
```

You can reuse the same command pattern for other wells and dates by changing the CSV path, image directory, and output directory.

## Outputs

- `*_all_image_matches.csv`: every parsed image, matched to the nearest corrected methane row when possible
- `*_overlap_image_matches.csv`: only images that fall inside the corrected methane time window
- `*_peak_photo_summary.csv`: methane peaks with the nearest available image
- `*_combined_event_report.csv`: one event-focused table that combines exact image matches, detected peaks, and the best image reference to review
- `*_duplicate_image_timestamps.csv`: duplicate image timestamps
- `*_unparsed_images.csv`: images that could not be matched because they lacked a usable timestamp

## Existing Well16 Wrapper

The dated folder still contains `Licor_7810/04_09_2026/well16_image_matching.py` as a convenience wrapper with the Well16 defaults preloaded.
