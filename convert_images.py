from PIL import Image
import numpy as np
import cv2
import os

folder = "referencePhoto"

for root, dirs, files in os.walk(folder):
    for fname in files:
        if fname.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):

            path = os.path.join(root, fname)

            try:
                # Step 1: open with PIL
                img = Image.open(path)

                # Step 2: force RGB
                img = img.convert("RGB")

                # Step 3: convert to numpy array
                img_np = np.array(img)

                # Step 4: force uint8 (VERY IMPORTANT)
                img_np = img_np.astype(np.uint8)

                # Step 5: save clean image using OpenCV
                new_path = os.path.splitext(path)[0] + ".jpg"
                cv2.imwrite(new_path, cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR))

                print("Fixed:", fname, "→", os.path.basename(new_path))

                # remove old file if different
                if new_path != path:
                    os.remove(path)

            except Exception as e:
                print("FAILED:", fname, e)