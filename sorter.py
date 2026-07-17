"""
sorter.py — Face recognition logic for KinderSort Lite.

PhotoSorter loads reference encodings and sorts event photos into per-student
output folders.  All processing is CPU-only (no GPU required).

Improvements over original KinderSort:
  1. Low-light image enhancement (gamma correction + brightness boost)
  2. Face alignment before encoding (eye-landmark-based rotation correction)
  3. Embedding cache (.pkl) — reference encodings saved to disk so subsequent
     runs skip the slow CNN encoding step entirely
"""

import hashlib
import logging
import math
import pickle
from collections.abc import Callable
from pathlib import Path

import face_recognition
import numpy as np
from PIL import Image, ImageEnhance, ImageOps, UnidentifiedImageError

from utils import (
    build_output_filename,
    collect_event_images,
    is_image_file,
    safe_copy,
)


class PhotoSorter:
    """Encapsulates the full sort pipeline from reference loading to file copying.

    Usage::

        sorter = PhotoSorter(reference_folder, events_folder, output_folder, logger)
        skipped_names = sorter.load_references()   # sync, may show warnings
        summary = sorter.sort_all(progress_cb, cancelled_cb)
    """

    DISTANCE_THRESHOLD = 0.55
    """Maximum face distance to consider a match (lower = stricter)."""

    MAX_IMAGE_DIMENSION = 1000
    """Longest side in pixels after resizing for face detection (performance)."""

    LOW_LIGHT_BRIGHTNESS_THRESHOLD = 70
    """Mean grayscale brightness (0-255) below which a photo is treated as
    under-exposed and enhanced. Chosen empirically — typical well-lit indoor
    photos average 110-180; genuinely dark event-hall photos fall below 70.
    A conservative threshold avoids accidentally enhancing normal photos,
    which can distort face encodings and reduce accuracy."""

    CACHE_FILENAME = ".kindersort_cache.pkl"
    """Hidden cache file stored inside the reference folder. Contains
    pre-computed 128-d face encodings keyed by (filename, md5_hash) so the
    cache is automatically invalidated when a reference photo is replaced."""

    def __init__(
        self,
        reference_folder: Path,
        events_folder: Path,
        output_folder: Path,
        logger: logging.Logger,
        enhance_images: bool = True,
        use_cache: bool = True,
    ) -> None:
        """Store folder paths and logger; initialise empty encoding dict.

        Args:
            enhance_images: If True, apply low-light enhancement (gamma
                correction + brightness boost) to under-exposed photos before
                face detection. Defaults to True.
            use_cache: If True, load/save reference encodings from a .pkl
                cache file in reference_folder. Subsequent runs skip the slow
                CNN encoding step, dramatically reducing startup time when the
                reference folder has not changed.
        """
        self.reference_folder = reference_folder
        self.events_folder = events_folder
        self.output_folder = output_folder
        self.logger = logger
        self.enhance_images = enhance_images
        self.use_cache = use_cache
        self._student_encodings: dict[str, np.ndarray] = {}

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _cache_path(self) -> Path:
        """Return the path to the embedding cache file."""
        return self.reference_folder / self.CACHE_FILENAME

    def _file_hash(self, path: Path) -> str:
        """Return the MD5 hex digest of a file (used as cache key)."""
        md5 = hashlib.md5()
        md5.update(path.read_bytes())
        return md5.hexdigest()

    def _load_cache(self) -> dict[str, np.ndarray]:
        """Load cached encodings from disk.

        Cache format: {(filename, md5): np.ndarray}
        Returns empty dict if cache missing, corrupt, or version-mismatched.
        """
        cache_path = self._cache_path()
        if not cache_path.exists():
            return {}
        try:
            with cache_path.open("rb") as f:
                data = pickle.load(f)
            if not isinstance(data, dict):
                return {}
            self.logger.info("Loaded embedding cache from %s", cache_path.name)
            return data
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Cache unreadable (%s) — will recompute", exc)
            return {}

    def _save_cache(self, cache: dict) -> None:
        """Write encoding cache to disk."""
        try:
            with self._cache_path().open("wb") as f:
                pickle.dump(cache, f)
            self.logger.info("Embedding cache saved to %s", self.CACHE_FILENAME)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Could not save cache: %s", exc)

    # ------------------------------------------------------------------
    # Reference loading
    # ------------------------------------------------------------------

    def load_references(
        self,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> list[str]:
        """Encode every reference photo and store by student name.

        Iterates over image files in reference_folder. The student name is
        the filename stem (e.g. ``Ali.jpg`` → ``"Ali"``).

        If use_cache=True, previously computed encodings are loaded from the
        .pkl cache. Only new or changed reference photos are re-encoded,
        saving significant time on subsequent runs.

        Args:
            progress_callback: Optional callable with ``(current, total, name)``
                called after each student is processed so the GUI can update.

        Returns:
            List of student names whose reference photo had no detectable face.
        """
        no_face_names: list[str] = []

        reference_images = sorted(
            p for p in self.reference_folder.iterdir() if is_image_file(p)
        )

        if not reference_images:
            self.logger.warning("No reference images found in %s", self.reference_folder)
            return no_face_names

        # Load existing cache
        cache: dict = self._load_cache() if self.use_cache else {}
        updated_cache: dict = {}
        cache_hits = 0

        total = len(reference_images)
        for current, ref_path in enumerate(reference_images, start=1):
            student_name = ref_path.stem
            if progress_callback:
                progress_callback(current, total, student_name)

            file_hash = self._file_hash(ref_path)
            cache_key = (ref_path.name, file_hash)

            # Cache hit — skip re-encoding
            if self.use_cache and cache_key in cache:
                encoding = cache[cache_key]
                if encoding is not None:
                    self._student_encodings[student_name] = encoding
                    updated_cache[cache_key] = encoding
                    cache_hits += 1
                    self.logger.info(
                        "Cache hit for %s — skipped re-encoding", student_name
                    )
                else:
                    no_face_names.append(student_name)
                    updated_cache[cache_key] = None
                continue

            # Cache miss — encode from scratch
            try:
                image = face_recognition.load_image_file(str(ref_path))

                # --- Face alignment ---
                pil_image = Image.fromarray(image)
                aligned = self._align_face(pil_image, ref_path.name)
                image = np.array(aligned)

                locations = face_recognition.face_locations(image, model="cnn")
                encodings = face_recognition.face_encodings(
                    image,
                    known_face_locations=locations,
                    num_jitters=10,
                    model="large",
                )

                if not encodings:
                    self.logger.warning(
                        "No face detected in reference photo for %s (%s)",
                        student_name,
                        ref_path.name,
                    )
                    no_face_names.append(student_name)
                    updated_cache[cache_key] = None
                    continue

                if len(encodings) > 1:
                    self.logger.warning(
                        "Multiple faces in reference photo for %s — using first face only",
                        student_name,
                    )

                self._student_encodings[student_name] = encodings[0]
                updated_cache[cache_key] = encodings[0]
                self.logger.info("Encoded reference for %s", student_name)

            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "Could not read reference photo %s: %s", ref_path.name, exc
                )

        if self.use_cache:
            self._save_cache(updated_cache)
            if cache_hits:
                self.logger.info(
                    "Cache saved %d re-encoding(s) (%d/%d from cache)",
                    cache_hits, cache_hits, total,
                )

        self.logger.info(
            "Loaded %d student reference(s)", len(self._student_encodings)
        )
        return no_face_names

    # ------------------------------------------------------------------
    # Main sort loop
    # ------------------------------------------------------------------

    def sort_all(
        self,
        progress_callback: Callable[[int, int, str], None],
        cancelled: Callable[[], bool],
    ) -> dict[str, int]:
        """Sort all event photos into per-student output subfolders.

        Processes one image at a time to keep RAM usage low. For each detected
        face in a photo the nearest student is identified; the photo is copied
        to every matched student folder (allowing group shots). Photos with no
        match or no face are copied to ``_unmatched/``.

        Args:
            progress_callback: Called with ``(current, total, filename)`` after
                each image so the GUI can update its progress bar.
            cancelled: Zero-arg callable; returns True if the user has cancelled.

        Returns:
            Dict with keys ``total``, ``matched``, ``unmatched``, ``skipped``.
        """
        images = collect_event_images(self.events_folder)
        total = len(images)
        counts = {"total": total, "matched": 0, "unmatched": 0, "skipped": 0}

        self.logger.info("Starting sort — %d images found", total)

        for current, (image_path, event_name) in enumerate(images, start=1):
            if cancelled():
                self.logger.info("Sort cancelled by user at image %d/%d", current, total)
                break

            progress_callback(current, total, image_path.name)
            output_filename = build_output_filename(event_name, image_path.name)

            try:
                rgb_image = self._load_and_resize(image_path)
            except UnidentifiedImageError:
                self.logger.warning(
                    "Corrupted image, moving to _unmatched: %s", image_path.name
                )
                safe_copy(
                    image_path,
                    self.output_folder / "_unmatched",
                    output_filename,
                    self.logger,
                )
                counts["unmatched"] += 1
                continue
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "Could not open %s: %s — skipping", image_path.name, exc
                )
                counts["skipped"] += 1
                continue

            try:
                face_locations = face_recognition.face_locations(rgb_image)  # HOG — fast
                if not face_locations:
                    face_locations = face_recognition.face_locations(
                        rgb_image, model="cnn"
                    )  # CNN fallback
                face_encodings = face_recognition.face_encodings(
                    rgb_image, face_locations, num_jitters=3, model="large"
                )
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "Face detection failed for %s: %s", image_path.name, exc
                )
                safe_copy(
                    image_path,
                    self.output_folder / "_unmatched",
                    output_filename,
                    self.logger,
                )
                counts["unmatched"] += 1
                continue

            if not face_encodings:
                self.logger.info("No face detected: %s → _unmatched", image_path.name)
                safe_copy(
                    image_path,
                    self.output_folder / "_unmatched",
                    output_filename,
                    self.logger,
                )
                counts["unmatched"] += 1
                continue

            matched_students: set[str] = set()
            for encoding in face_encodings:
                match = self._match_face(encoding)
                if match:
                    matched_students.add(match)

            if matched_students:
                for student_name in matched_students:
                    dest_folder = self.output_folder / student_name
                    safe_copy(image_path, dest_folder, output_filename, self.logger)
                    self.logger.info("Matched %s → %s", image_path.name, student_name)
                counts["matched"] += 1
            else:
                self.logger.info("No match: %s → _unmatched", image_path.name)
                safe_copy(
                    image_path,
                    self.output_folder / "_unmatched",
                    output_filename,
                    self.logger,
                )
                counts["unmatched"] += 1

        self.logger.info(
            "Sort complete — total=%d matched=%d unmatched=%d skipped=%d",
            counts["total"],
            counts["matched"],
            counts["unmatched"],
            counts["skipped"],
        )
        return counts

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_and_resize(self, image_path: Path) -> np.ndarray:
        """Open image with Pillow, resize if needed, and return as RGB numpy array.

        Resizing large images to at most MAX_IMAGE_DIMENSION on the longest side
        dramatically reduces face_locations() time on CPU without meaningfully
        reducing recognition accuracy.

        If ``self.enhance_images`` is True, under-exposed photos are enhanced
        before face detection (see ``_enhance_low_light``).

        Raises:
            UnidentifiedImageError: If Pillow cannot read the file format.
        """
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            width, height = img.size
            longest = max(width, height)
            if longest > self.MAX_IMAGE_DIMENSION:
                scale = self.MAX_IMAGE_DIMENSION / longest
                new_size = (int(width * scale), int(height * scale))
                img = img.resize(new_size, Image.LANCZOS)

            if self.enhance_images:
                img = self._enhance_low_light(img, image_path.name)

            return np.array(img)

    def _enhance_low_light(self, img: Image.Image, filename: str) -> Image.Image:
        """Brighten under-exposed images using gamma correction and brightness boost.

        Unlike global histogram equalisation (which redistributes pixel values
        aggressively and can distort face colour balance), this approach applies
        gamma correction followed by a proportional brightness boost. This preserves
        skin-tone and facial feature colours so face encodings stay consistent with
        well-lit reference photos.

        Only photos below LOW_LIGHT_BRIGHTNESS_THRESHOLD are touched.
        """
        grayscale = img.convert("L")
        mean_brightness = float(np.array(grayscale).mean())

        if mean_brightness < self.LOW_LIGHT_BRIGHTNESS_THRESHOLD:
            boost_factor = min(120.0 / max(mean_brightness, 1.0), 4.0)
            self.logger.debug(
                "Low-light detected (mean=%.1f < %d): %s — boost x%.2f",
                mean_brightness,
                self.LOW_LIGHT_BRIGHTNESS_THRESHOLD,
                filename,
                boost_factor,
            )
            arr = np.array(img).astype(np.float32) / 255.0
            arr = np.power(arr, 0.6)
            gamma_img = Image.fromarray((arr * 255).clip(0, 255).astype(np.uint8))
            return ImageEnhance.Brightness(gamma_img).enhance(boost_factor * 0.5)

        return img

    def _align_face(self, img: Image.Image, filename: str) -> Image.Image:
        """Rotate image so the eyes are horizontally level (face alignment).

        Face alignment reduces variation caused by head tilt, improving
        encoding consistency between reference photos and event photos taken
        from different angles.

        Uses face_recognition.face_landmarks() to locate the left and right
        eye centres, then rotates the image so the eye-line is horizontal.
        If no landmarks are detected the original image is returned unchanged.

        Args:
            img: RGB PIL Image.
            filename: Used only for debug logging.

        Returns:
            Aligned (possibly rotated) PIL Image, same size as input.
        """
        arr = np.array(img)
        landmarks_list = face_recognition.face_landmarks(arr)

        if not landmarks_list:
            self.logger.debug("No landmarks for alignment in %s — skipping", filename)
            return img

        # Use the first (most prominent) face
        landmarks = landmarks_list[0]

        left_eye_pts = landmarks.get("left_eye", [])
        right_eye_pts = landmarks.get("right_eye", [])

        if not left_eye_pts or not right_eye_pts:
            return img

        # Compute eye centres
        left_cx = sum(p[0] for p in left_eye_pts) / len(left_eye_pts)
        left_cy = sum(p[1] for p in left_eye_pts) / len(left_eye_pts)
        right_cx = sum(p[0] for p in right_eye_pts) / len(right_eye_pts)
        right_cy = sum(p[1] for p in right_eye_pts) / len(right_eye_pts)

        # Angle of the eye line relative to horizontal
        dx = right_cx - left_cx
        dy = right_cy - left_cy
        angle_deg = math.degrees(math.atan2(dy, dx))

        # Only rotate if tilt is more than 1° (avoids unnecessary resampling)
        if abs(angle_deg) < 1.0:
            return img

        self.logger.debug(
            "Aligning face in %s — rotating %.1f°", filename, -angle_deg
        )
        return img.rotate(-angle_deg, resample=Image.BICUBIC, expand=False)

    def _match_face(self, encoding: np.ndarray) -> str | None:
        """Find the closest student encoding within DISTANCE_THRESHOLD.

        Uses face_distance() + argmin rather than compare_faces() booleans so
        each detected face always matches at most one student — the nearest one.

        Args:
            encoding: 128-d face encoding from face_recognition.

        Returns:
            Student name string if a match is found, otherwise None.
        """
        if not self._student_encodings:
            return None

        names = list(self._student_encodings.keys())
        known_encodings = np.array(list(self._student_encodings.values()))

        distances = face_recognition.face_distance(known_encodings, encoding)
        best_idx = int(np.argmin(distances))
        best_distance = distances[best_idx]

        if best_distance <= self.DISTANCE_THRESHOLD:
            self.logger.debug(
                "Face matched to %s (distance=%.4f)", names[best_idx], best_distance
            )
            return names[best_idx]

        self.logger.debug("No match — best distance=%.4f", best_distance)
        return None