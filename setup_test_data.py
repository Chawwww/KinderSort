"""
setup_test_data.py — Auto-organise LFW dataset into KinderSort folder structure.

Run this ONCE after downloading the LFW dataset zip from Kaggle.

Usage:
    1. Extract the Kaggle zip — you will get a folder like "lfw-deepfunneled" or "lfw"
    2. Edit LFW_FOLDER below to point to that folder
    3. Run:  python setup_test_data.py

What this script does:
    - Picks 5 people from LFW who have enough photos
    - Puts their FIRST photo into referencePhoto/  (named by person, e.g. Person1.jpg)
    - Puts their REMAINING photos into Events/Sports_Day/
    - Also adds 2 dark/dim photos (artificially darkened) to test the enhancement
    - Creates benchmark_data/ground_truth.csv automatically

After running, your folders will be ready and you can:
    1. Open KinderSort GUI and do a test sort
    2. Run benchmark.py to get baseline vs improved accuracy numbers
"""

import csv
import random
import shutil
from pathlib import Path
from PIL import Image, ImageEnhance
import numpy as np

# -----------------------------------------------------------------------
# EDIT THIS LINE: point to the folder you extracted from the Kaggle zip
# Example: r"C:\Users\yourname\Downloads\lfw-deepfunneled\lfw-deepfunneled"
# -----------------------------------------------------------------------
LFW_FOLDER = r"C:\Users\zhenh\Downloads\archive\lfw-deepfunneled\lfw-deepfunneled"   # <-- CHANGE THIS

# How many "students" to pick from LFW
NUM_STUDENTS = 5

# How many event photos per student (from their extra LFW photos)
PHOTOS_PER_STUDENT = 3

# -----------------------------------------------------------------------
HERE = Path(__file__).parent.resolve()
REF_FOLDER = HERE / "referencePhoto"
EVENTS_FOLDER = HERE / "Events" / "Sports_Day"
BENCHMARK_DIR = HERE / "benchmark_data"
GROUND_TRUTH_CSV = BENCHMARK_DIR / "ground_truth.csv"


def pick_students(lfw_path: Path, num: int, min_photos: int) -> list[Path]:
    """Return folders (people) that have at least min_photos images."""
    candidates = [
        d for d in sorted(lfw_path.iterdir())
        if d.is_dir() and len(list(d.glob("*.jpg"))) >= min_photos
    ]
    if len(candidates) < num:
        raise SystemExit(
            f"Not enough people with {min_photos}+ photos in {lfw_path}.\n"
            f"Found {len(candidates)}, need {num}.\n"
            "Try reducing NUM_STUDENTS or PHOTOS_PER_STUDENT."
        )
    random.seed(42)  # fixed seed → reproducible selection
    return random.sample(candidates, num)


def darken_image(src: Path, dest: Path, brightness: float = 0.25) -> None:
    """Save a darkened copy of src to dest (simulates low-light event photo)."""
    with Image.open(src) as img:
        img = img.convert("RGB")
        darkened = ImageEnhance.Brightness(img).enhance(brightness)
        darkened.save(str(dest))


def main() -> None:
    lfw_path = Path(LFW_FOLDER)
    if not lfw_path.exists():
        raise SystemExit(
            f"LFW folder not found: {lfw_path}\n"
            "Please edit the LFW_FOLDER variable at the top of this script."
        )

    # Clean and recreate output folders
    for folder in [REF_FOLDER, EVENTS_FOLDER, BENCHMARK_DIR]:
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)

    print(f"LFW source  : {lfw_path}")
    print(f"Picking {NUM_STUDENTS} students with {PHOTOS_PER_STUDENT + 1}+ photos each...\n")

    students = pick_students(lfw_path, NUM_STUDENTS, PHOTOS_PER_STUDENT + 1)

    ground_truth: list[dict] = []
    dark_photos: list[tuple[str, str]] = []  # (dest_filename, student_name)

    for person_folder in students:
        photos = sorted(person_folder.glob("*.jpg"))
        student_name = person_folder.name.replace("_", " ")

        # --- Reference photo (first photo) ---
        ref_dest = REF_FOLDER / f"{student_name}.jpg"
        shutil.copy2(photos[0], ref_dest)
        print(f"  Reference : {ref_dest.name}")

        # --- Event photos (next PHOTOS_PER_STUDENT photos) ---
        for photo in photos[1: PHOTOS_PER_STUDENT + 1]:
            dest_name = f"{student_name}_{photo.name}"
            dest = EVENTS_FOLDER / dest_name
            shutil.copy2(photo, dest)
            ground_truth.append({
                "filename": dest_name,
                "expected_students": student_name,
            })
            print(f"    Event   : {dest_name}")

        # --- One artificially darkened photo per student ---
        dark_src = photos[PHOTOS_PER_STUDENT + 1] if len(photos) > PHOTOS_PER_STUDENT + 1 else photos[1]
        dark_name = f"DARK_{student_name}_{dark_src.name}"
        darken_image(dark_src, EVENTS_FOLDER / dark_name)
        dark_photos.append((dark_name, student_name))
        print(f"    Dark    : {dark_name}  (artificially darkened)")

    # Add dark photos to ground truth
    for dark_name, student_name in dark_photos:
        ground_truth.append({
            "filename": dark_name,
            "expected_students": student_name,
        })

    # Add 2 "no face / unmatched" entries using landscape-like crops
    # (we just use a photo from a person NOT in our student list as unmatched)
    all_people = [d for d in lfw_path.iterdir() if d.is_dir()]
    non_students = [d for d in all_people if d not in students]
    random.shuffle(non_students)
    unmatched_count = 0
    for person_folder in non_students:
        photos = list(person_folder.glob("*.jpg"))
        if photos:
            dest_name = f"UNMATCHED_{person_folder.name}_{photos[0].name}"
            shutil.copy2(photos[0], EVENTS_FOLDER / dest_name)
            ground_truth.append({
                "filename": dest_name,
                "expected_students": "",  # should go to _unmatched
            })
            print(f"  Unmatched: {dest_name}")
            unmatched_count += 1
            if unmatched_count >= 2:
                break

    # Write ground_truth.csv
    with GROUND_TRUTH_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["filename", "expected_students"])
        writer.writeheader()
        writer.writerows(ground_truth)

    print(f"\n✅ Done!")
    print(f"   referencePhoto/ : {NUM_STUDENTS} student reference photos")
    print(f"   Events/Sports_Day/ : {len(list(EVENTS_FOLDER.iterdir()))} event photos")
    print(f"   benchmark_data/ground_truth.csv : {len(ground_truth)} rows")
    print(f"\nNext steps:")
    print(f"  1. Open KinderSort GUI → select referencePhoto/, Events/, any Output folder → Start Sorting")
    print(f"  2. Run:  python benchmark.py")


if __name__ == "__main__":
    main()
