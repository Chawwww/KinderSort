# KinderSort — Student Photo Organiser

[中文说明 (简体)](README.zh-CN.md)

KinderSort is an offline desktop app for kindergarten teachers. It scans event photos, matches student faces, and copies each photo into the correct student folder automatically.

## Highlights

- Fully offline (no cloud upload required)
- CPU-only face recognition (`face_recognition` + `dlib`)
- Simple `tkinter` GUI for non-technical users
- Group photos are copied to all matched students
- Unmatched photos are copied to `_unmatched`
- Detailed log file written to `kindersort_log.txt`

## Who this is for

- Teachers who need to organise large batches of student photos quickly
- Schools that require local/offline processing for privacy

## Input folder structure

You choose three folders in the app:

1. **Reference Photos**: one clear front-facing photo per student, file name = student name  
   Example: `Ali.jpg`, `Siti.png`, `Kumar.jpeg`
2. **Events Folder**: contains event subfolders with mixed photos  
   Example: `Sports_Day/`, `Concert/`, `Field_Trip/`
3. **Output Folder**: destination for sorted results

## Output structure

```text
Output/
  Ali/
    Sports_Day__IMG_001.jpg
  Siti/
    Sports_Day__IMG_001.jpg
  _unmatched/
    blurry_photo.jpg
  kindersort_log.txt
```

## How to use (Teacher quick start)

1. Download `KinderSort.exe` from the project **Releases** page.
2. Double-click `KinderSort.exe`.
3. Select the three folders (Reference / Events / Output).
4. Click **Start Sorting**.
5. Review the summary and open the Output folder.

Full illustrated teacher guide: [`guidebook.md`](guidebook.md)

## Screenshot walkthrough

### 1) App launch

![KinderSort launch](guidebook_assets/01_launch.png)

### 2) Reference folder selected

![Reference folder selected](guidebook_assets/02_reference_selected.png)

### 3) Events folder selected

![Events folder selected](guidebook_assets/03_events_selected.png)

### 4) All folders ready

![All folders set](guidebook_assets/04_all_folders_set.png)

### 5) Sorting in progress

![Sorting in progress](guidebook_assets/05_sorting_in_progress.png)

### 6) Sorting complete summary

![Sorting complete](guidebook_assets/06_sorting_complete.png)

## Important behavior

- Distance threshold is `0.5` (strict matching to reduce false positives).
- Files are copied (not moved).
- Photos directly in the Events root are skipped; photos should be inside event subfolders.
- If reference photo has no face, that student is skipped with a warning.

## Downloading the EXE

Please download prebuilt Windows binaries from:

- **Releases**: `https://github.com/lerlerchan/KinderSort/releases`

We intentionally keep `.exe` files out of normal Git history to keep the repository lightweight.

## Developer setup (from source)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Build Windows executable:

```bash
pyinstaller --onefile --windowed --name "KinderSort" main.py
```

## Tech stack

- Python 3.10+
- `face_recognition`
- `dlib`
- `Pillow`
- `numpy`
- `tkinter`
- `PyInstaller`
