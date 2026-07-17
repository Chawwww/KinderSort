"""
sorter.py — Face recognition logic for KinderSort Lite.

PhotoSorter loads reference encodings and sorts event photos into per-student
output folders.  All processing is CPU-only (no GPU required).

Improvements over original KinderSort:
  1. OpenCV DNN face detection (replaces HOG/CNN — more accurate on small,
     tilted, and dark faces; uses res10_300x300_ssd deep learning model)
  2. Low-light image enhancement (gamma correction + brightness boost)
  3. Face alignment before encoding (eye-landmark rotation correction)
  4. Embedding cache (.pkl) — reference encodings saved to disk so subsequent
     runs skip the slow CNN encoding step entirely
"""

import hashlib
import logging
import math
import pickle
from collections.abc import Callable
from pathlib import Path

import cv2
import face_recognition
import numpy as np
from PIL import Image, ImageEnhance, ImageOps, UnidentifiedImageError

from utils import (
    build_output_filename,
    collect_event_images,
    is_image_file,
    safe_copy,
)

# Path to OpenCV DNN model files (stored in models/ subfolder of the project)
_MODEL_DIR = Path(__file__).parent / "models"
_PROTOTXT  = _MODEL_DIR / "deploy.prototxt"
_CAFFEMODEL = _MODEL_DIR / "res10_300x300_ssd_iter_140000.caffemodel"


class PhotoSorter:
    """Encapsulates the full sort pipeline from reference loading to file copying."""

    DISTANCE_THRESHOLD = 0.55
    MAX_IMAGE_DIMENSION = 1000
    LOW_LIGHT_BRIGHTNESS_THRESHOLD = 70
    OPENCV_CONFIDENCE_THRESHOLD = 0.5
    """Minimum confidence score for OpenCV DNN detections (0.0–1.0).
    Detections below this threshold are discarded as false positives."""

    CACHE_FILENAME = ".kindersort_cache.pkl"

    def __init__(
        self,
        reference_folder: Path,
        events_folder: Path,
        output_folder: Path,
        logger: logging.Logger,
        enhance_images: bool = True,
        use_cache: bool = True,
    ) -> None:
        self.reference_folder = reference_folder
        self.events_folder = events_folder
        self.output_folder = output_folder
        self.logger = logger
        self.enhance_images = enhance_images
        self.use_cache = use_cache
        self._student_encodings: dict[str, np.ndarray] = {}
        self._opencv_net = None  # loaded lazily on first use

    # ------------------------------------------------------------------
    # OpenCV DNN face detector
    # ------------------------------------------------------------------

    def _get_opencv_net(self):
        """Load the OpenCV DNN face detection model (lazy, loaded once).

        Uses the res10_300x300_ssd deep learning model — a Single Shot
        Multibox Detector trained on ResNet-10. Compared to dlib's HOG model,
        it detects faces at greater angles, smaller sizes, and lower contrast
        (useful for dark event photos), while remaining fast enough for
        CPU-only use.

        Returns None if model files are missing (falls back to HOG/CNN).
        """
        if self._opencv_net is not None:
            return self._opencv_net

        if not _PROTOTXT.exists() or not _CAFFEMODEL.exists():
            self.logger.warning(
                "OpenCV DNN model files not found in models/ — "
                "falling back to dlib HOG detection. "
                "Run: python download_models.py"
            )
            return None

        self.logger.info("Loading OpenCV DNN face detector from models/")
        self._opencv_net = cv2.dnn.readNetFromCaffe(
            str(_PROTOTXT), str(_CAFFEMODEL)
        )
        # Force CPU mode explicitly (no CUDA)
        self._opencv_net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self._opencv_net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        return self._opencv_net

    def _detect_faces_opencv(self, rgb_image: np.ndarray) -> list[tuple]:
        """Detect faces using OpenCV DNN and return face_recognition-format locations.

        OpenCV DNN operates on BGR images with a 300×300 blob input. Detected
        bounding boxes are scaled back to the original image dimensions.

        Args:
            rgb_image: H×W×3 numpy array in RGB order.

        Returns:
            List of (top, right, bottom, left) tuples in CSS order, as
            expected by face_recognition.face_encodings(). Returns empty
            list if no faces found or model unavailable.
        """
        net = self._get_opencv_net()
        if net is None:
            return []

        # Convert RGB → BGR for OpenCV
        bgr = cv2.cvtColor(rgb_image, cv2.COLOR_RGB2BGR)
        h, w = bgr.shape[:2]

        blob = cv2.dnn.blobFromImage(
            cv2.resize(bgr, (300, 300)),
            scalefactor=1.0,
            size=(300, 300),
            mean=(104.0, 177.0, 123.0),
        )
        net.setInput(blob)
        detections = net.forward()

        locations = []
        for i in range(detections.shape[2]):
            confidence = float(detections[0, 0, i, 2])
            if confidence < self.OPENCV_CONFIDENCE_THRESHOLD:
                continue

            box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
            startX, startY, endX, endY = box.astype(int)

            # Clamp to image bounds
            startX = max(0, startX)
            startY = max(0, startY)
            endX   = min(w, endX)
            endY   = min(h, endY)

            if endX <= startX or endY <= startY:
                continue

            # Convert to face_recognition CSS format: (top, right, bottom, left)
            locations.append((startY, endX, endY, startX))

            self.logger.debug(
                "OpenCV DNN detected face: conf=%.2f box=(%d,%d,%d,%d)",
                confidence, startX, startY, endX, endY,
            )

        return locations

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _cache_path(self) -> Path:
        return self.reference_folder / self.CACHE_FILENAME

    def _file_hash(self, path: Path) -> str:
        md5 = hashlib.md5()
        md5.update(path.read_bytes())
        return md5.hexdigest()

    def _load_cache(self) -> dict:
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

        Uses OpenCV DNN for face detection on reference photos (more accurate
        than HOG for the controlled single-face reference images). Falls back
        to dlib CNN if OpenCV model is unavailable.

        Results are cached to disk so subsequent runs skip re-encoding.
        """
        no_face_names: list[str] = []

        reference_images = sorted(
            p for p in self.reference_folder.iterdir() if is_image_file(p)
        )
        if not reference_images:
            self.logger.warning("No reference images found in %s", self.reference_folder)
            return no_face_names

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

            if self.use_cache and cache_key in cache:
                encoding = cache[cache_key]
                if encoding is not None:
                    self._student_encodings[student_name] = encoding
                    cache_hits += 1
                    self.logger.info("Cache hit for %s — skipped re-encoding", student_name)
                else:
                    no_face_names.append(student_name)
                updated_cache[cache_key] = encoding
                continue

            try:
                image = face_recognition.load_image_file(str(ref_path))

                # Align face before encoding
                pil_image = Image.fromarray(image)
                aligned = self._align_face(pil_image, ref_path.name)
                image = np.array(aligned)

                # Try OpenCV DNN detection first, fall back to CNN
                locations = self._detect_faces_opencv(image)
                if not locations:
                    self.logger.debug(
                        "OpenCV found no face in %s — trying dlib CNN", ref_path.name
                    )
                    locations = face_recognition.face_locations(image, model="cnn")

                encodings = face_recognition.face_encodings(
                    image,
                    known_face_locations=locations,
                    num_jitters=10,
                    model="large",
                )

                if not encodings:
                    self.logger.warning(
                        "No face detected in reference photo for %s", student_name
                    )
                    no_face_names.append(student_name)
                    updated_cache[cache_key] = None
                    continue

                if len(encodings) > 1:
                    self.logger.warning(
                        "Multiple faces in %s — using first face only", ref_path.name
                    )

                self._student_encodings[student_name] = encodings[0]
                updated_cache[cache_key] = encodings[0]
                self.logger.info("Encoded reference for %s", student_name)

            except Exception as exc:  # noqa: BLE001
                self.logger.error("Could not read %s: %s", ref_path.name, exc)

        if self.use_cache:
            self._save_cache(updated_cache)
            if cache_hits:
                self.logger.info(
                    "%d/%d references loaded from cache", cache_hits, total
                )

        self.logger.info("Loaded %d student reference(s)", len(self._student_encodings))
        return no_face_names

    # ------------------------------------------------------------------
    # Main sort loop
    # ------------------------------------------------------------------

    def sort_all(
        self,
        progress_callback: Callable[[int, int, str], None],
        cancelled: Callable[[], bool],
    ) -> dict[str, int]:
        """Sort all event photos into per-student output subfolders."""
        images = collect_event_images(self.events_folder)
        total = len(images)
        counts = {"total": total, "matched": 0, "unmatched": 0, "skipped": 0}

        self.logger.info("Starting sort — %d images found", total)

        for current, (image_path, event_name) in enumerate(images, start=1):
            if cancelled():
                self.logger.info("Sort cancelled at image %d/%d", current, total)
                break

            progress_callback(current, total, image_path.name)
            output_filename = build_output_filename(event_name, image_path.name)

            try:
                rgb_image = self._load_and_resize(image_path)
            except UnidentifiedImageError:
                self.logger.warning("Corrupted image → _unmatched: %s", image_path.name)
                safe_copy(image_path, self.output_folder / "_unmatched", output_filename, self.logger)
                counts["unmatched"] += 1
                continue
            except Exception as exc:  # noqa: BLE001
                self.logger.error("Could not open %s: %s", image_path.name, exc)
                counts["skipped"] += 1
                continue

            try:
                # OpenCV DNN detection first (more accurate for event photos)
                face_locations = self._detect_faces_opencv(rgb_image)

                # Fallback 1: dlib HOG (fast)
                if not face_locations:
                    face_locations = face_recognition.face_locations(rgb_image)

                # Fallback 2: dlib CNN (slow but most accurate)
                if not face_locations:
                    face_locations = face_recognition.face_locations(
                        rgb_image, model="cnn"
                    )

                face_encodings = face_recognition.face_encodings(
                    rgb_image, face_locations, num_jitters=3, model="large"
                )
            except Exception as exc:  # noqa: BLE001
                self.logger.error("Face detection failed for %s: %s", image_path.name, exc)
                safe_copy(image_path, self.output_folder / "_unmatched", output_filename, self.logger)
                counts["unmatched"] += 1
                continue

            if not face_encodings:
                self.logger.info("No face detected: %s → _unmatched", image_path.name)
                safe_copy(image_path, self.output_folder / "_unmatched", output_filename, self.logger)
                counts["unmatched"] += 1
                continue

            matched_students: set[str] = set()
            for encoding in face_encodings:
                match = self._match_face(encoding)
                if match:
                    matched_students.add(match)

            if matched_students:
                for student_name in matched_students:
                    safe_copy(image_path, self.output_folder / student_name, output_filename, self.logger)
                    self.logger.info("Matched %s → %s", image_path.name, student_name)
                counts["matched"] += 1
            else:
                self.logger.info("No match: %s → _unmatched", image_path.name)
                safe_copy(image_path, self.output_folder / "_unmatched", output_filename, self.logger)
                counts["unmatched"] += 1

        self.logger.info(
            "Sort complete — total=%d matched=%d unmatched=%d skipped=%d",
            counts["total"], counts["matched"], counts["unmatched"], counts["skipped"],
        )
        return counts

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_and_resize(self, image_path: Path) -> np.ndarray:
        """Open, resize, and optionally enhance an event photo."""
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            w, h = img.size
            longest = max(w, h)
            if longest > self.MAX_IMAGE_DIMENSION:
                scale = self.MAX_IMAGE_DIMENSION / longest
                img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
            if self.enhance_images:
                img = self._enhance_low_light(img, image_path.name)
            return np.array(img)

    def _enhance_low_light(self, img: Image.Image, filename: str) -> Image.Image:
        """Apply gamma correction + brightness boost to under-exposed photos."""
        mean_brightness = float(np.array(img.convert("L")).mean())
        if mean_brightness < self.LOW_LIGHT_BRIGHTNESS_THRESHOLD:
            boost = min(120.0 / max(mean_brightness, 1.0), 4.0)
            self.logger.debug(
                "Low-light (mean=%.1f): %s — boost x%.2f", mean_brightness, filename, boost
            )
            arr = np.array(img).astype(np.float32) / 255.0
            arr = np.power(arr, 0.6)
            gamma_img = Image.fromarray((arr * 255).clip(0, 255).astype(np.uint8))
            return ImageEnhance.Brightness(gamma_img).enhance(boost * 0.5)
        return img

    def _align_face(self, img: Image.Image, filename: str) -> Image.Image:
        """Rotate image so eyes are horizontal (reduces encoding variation)."""
        arr = np.array(img)
        landmarks_list = face_recognition.face_landmarks(arr)
        if not landmarks_list:
            return img
        landmarks = landmarks_list[0]
        left_pts = landmarks.get("left_eye", [])
        right_pts = landmarks.get("right_eye", [])
        if not left_pts or not right_pts:
            return img
        lx = sum(p[0] for p in left_pts) / len(left_pts)
        ly = sum(p[1] for p in left_pts) / len(left_pts)
        rx = sum(p[0] for p in right_pts) / len(right_pts)
        ry = sum(p[1] for p in right_pts) / len(right_pts)
        angle = math.degrees(math.atan2(ry - ly, rx - lx))
        if abs(angle) < 1.0:
            return img
        self.logger.debug("Aligning %s — rotating %.1f°", filename, -angle)
        return img.rotate(-angle, resample=Image.BICUBIC, expand=False)

    def _match_face(self, encoding: np.ndarray) -> str | None:
        """Return the closest matching student name, or None if no match."""
        if not self._student_encodings:
            return None
        names = list(self._student_encodings.keys())
        known = np.array(list(self._student_encodings.values()))
        distances = face_recognition.face_distance(known, encoding)
        best_idx = int(np.argmin(distances))
        if distances[best_idx] <= self.DISTANCE_THRESHOLD:
            return names[best_idx]
        return None