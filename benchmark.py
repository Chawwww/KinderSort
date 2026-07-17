"""
benchmark.py — Compare baseline vs improved (low-light enhanced) accuracy.

HOW TO USE THIS SCRIPT
-----------------------
This version reuses your EXISTING folders — no need to create a separate
benchmark_data/reference or benchmark_data/events copy:

    referencePhoto/        <- your existing student reference photos
    Events/                 <- your existing event subfolders with photos
    benchmark_data/
        ground_truth.csv    <- the ONLY new file you need to create

1. Put some test photos into your existing Events/<some_subfolder>/ —
   ideally a mix of: a few clearly-lit photos, a few deliberately dark/
   under-exposed photos (to show the improvement), a group photo or two,
   and a photo or two with no recognisable student face.

2. Create benchmark_data/ground_truth.csv (one row per test photo):

       filename,expected_students
       IMG_001.jpg,Ali;Siti
       IMG_002.jpg,Kumar
       IMG_003.jpg,

   - filename must match the original filename inside Events/<event>/
   - expected_students: semicolon-separated list of student names that
     SHOULD be matched in this photo (group photos can list multiple names)
   - Leave empty for photos that should land in _unmatched (no faces /
     no recognisable student — e.g. teacher-only shots, blurry photos)

   Only photos listed in this CSV are scored — any other photos sitting in
   Events/ are simply ignored by the benchmark (so it's safe to test against
   your full existing Events/ folder without curating a separate copy).

3. Run:

       python benchmark.py

   This runs the sorter TWICE on the same test set — once with
   enhance_images=False (baseline) and once with enhance_images=True
   (improved) — and prints a side-by-side accuracy comparison table that
   you can paste straight into your report.
"""

import csv
import logging
import shutil
import time
from pathlib import Path

from sorter import PhotoSorter

HERE = Path(__file__).parent.resolve()

# Reuses your existing project folders directly — no duplicate copies needed.
REFERENCE_FOLDER = HERE / "referencePhoto"
EVENTS_FOLDER = HERE / "Events"

DATA_DIR = HERE / "benchmark_data"
GROUND_TRUTH_CSV = DATA_DIR / "ground_truth.csv"


def load_ground_truth() -> dict[str, set[str]]:
    """Read ground_truth.csv into {filename: {expected student names}}."""
    truth: dict[str, set[str]] = {}
    with GROUND_TRUTH_CSV.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            names = {n.strip() for n in row["expected_students"].split(";") if n.strip()}
            truth[row["filename"]] = names
    return truth


def run_one_pass(enhance_images: bool, output_folder: Path) -> dict:
    """Run the full sort pipeline once and return per-photo predicted matches."""
    if output_folder.exists():
        shutil.rmtree(output_folder)
    output_folder.mkdir(parents=True)

    logger = logging.getLogger(f"benchmark_{'improved' if enhance_images else 'baseline'}")
    logger.setLevel(logging.WARNING)  # keep console quiet during benchmark
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())

    sorter = PhotoSorter(REFERENCE_FOLDER, EVENTS_FOLDER, output_folder, logger, enhance_images=enhance_images)
    sorter.load_references()

    start = time.monotonic()
    sorter.sort_all(progress_callback=lambda *_: None, cancelled=lambda: False)
    elapsed = time.monotonic() - start

    # Work out which students each output photo landed in, by scanning the
    # output folder structure (mirrors what the real app produces).
    predicted: dict[str, set[str]] = {}
    for student_folder in output_folder.iterdir():
        if not student_folder.is_dir() or student_folder.name == "_unmatched":
            continue
        for photo in student_folder.iterdir():
            # output filenames are "<event>__<original_filename>"
            original_name = photo.name.split("__", 1)[-1]
            predicted.setdefault(original_name, set()).add(student_folder.name)

    return {"predicted": predicted, "elapsed": elapsed}


def score(ground_truth: dict[str, set[str]], predicted: dict[str, set[str]]) -> dict:
    """Compute per-photo exact-match accuracy plus precision/recall on student labels."""
    correct_photos = 0
    total_photos = len(ground_truth)

    true_positives = 0
    false_positives = 0
    false_negatives = 0

    for filename, expected in ground_truth.items():
        got = predicted.get(filename, set())
        if got == expected:
            correct_photos += 1
        true_positives += len(got & expected)
        false_positives += len(got - expected)
        false_negatives += len(expected - got)

    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) else 1.0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) else 1.0

    return {
        "photo_exact_match_accuracy": correct_photos / total_photos if total_photos else 0.0,
        "precision": precision,
        "recall": recall,
        "correct_photos": correct_photos,
        "total_photos": total_photos,
    }


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    if not GROUND_TRUTH_CSV.exists():
        raise SystemExit(
            f"Missing {GROUND_TRUTH_CSV}.\nSee the module docstring at the top of this "
            "file for the CSV format you need to create first."
        )

    ground_truth = load_ground_truth()

    print("Running BASELINE pass (enhance_images=False)...")
    baseline = run_one_pass(enhance_images=False, output_folder=DATA_DIR / "output_baseline")
    baseline_scores = score(ground_truth, baseline["predicted"])

    print("Running IMPROVED pass (enhance_images=True)...")
    improved = run_one_pass(enhance_images=True, output_folder=DATA_DIR / "output_improved")
    improved_scores = score(ground_truth, improved["predicted"])

    print("\n" + "=" * 60)
    print(f"{'Metric':<32}{'Baseline':>12}{'Improved':>14}")
    print("=" * 60)
    print(f"{'Photo exact-match accuracy':<32}{baseline_scores['photo_exact_match_accuracy']:>11.1%} {improved_scores['photo_exact_match_accuracy']:>13.1%}")
    print(f"{'Precision':<32}{baseline_scores['precision']:>11.1%} {improved_scores['precision']:>13.1%}")
    print(f"{'Recall':<32}{baseline_scores['recall']:>11.1%} {improved_scores['recall']:>13.1%}")
    print(f"{'Correct / total photos':<32}{baseline_scores['correct_photos']}/{baseline_scores['total_photos']:<8}{improved_scores['correct_photos']}/{improved_scores['total_photos']}")
    print(f"{'Time taken (seconds)':<32}{baseline['elapsed']:>11.1f} {improved['elapsed']:>13.1f}")
    print("=" * 60)
    print("\nCopy this table into your report's Performance Evaluation section.")


if __name__ == "__main__":
    main()