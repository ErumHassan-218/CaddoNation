# Methane Data Matching

This repo root now includes a reusable CLI for matching methane CSV timestamps to field images.

## Generic CLI

Run from the `Methane_Data` repo root:

```bash
python3 methane_image_matching.py \
  --csv-path Licor_7810/04_09_2026/Well16.csv \
  --image-dir "../Wells/W16/Field Visit Data/Field Pictures" \
  --output-dir Licor_7810/04_09_2026/outputs
```

You can reuse the same command pattern for other wells and dates by changing the CSV path, image directory, and output directory.

## Existing Well16 Wrapper

The dated folder still contains `Licor_7810/04_09_2026/well16_image_matching.py` as a convenience wrapper with the Well16 defaults preloaded.
