"""
Crops the sheet to the frame drawn by the four solid L-shaped marks printed at
its corners, so the template is applied in the marks' coordinates and no longer
depends on how the scanner positioned, rotated or scaled the page.
"""
import cv2
import numpy as np

from src.constants.image_processing import (
    CORNER_MARK_MAX_ASPECT_RATIO,
    CORNER_MARK_MAX_SIDE_MISMATCH,
    CORNER_MARK_SOLIDITY_RANGE,
    DEFAULT_CORNER_MARK_SIZE_RANGE,
    DEFAULT_CORNER_SEARCH_REGION,
)
from src.logger import logger
from src.processors.interfaces.ImagePreprocessor import ImagePreprocessor
from src.utils.image import ImageUtils
from src.utils.interaction import InteractionUtils

CORNER_NAMES = ["top-left", "top-right", "bottom-right", "bottom-left"]


class CropOnCornerMarks(ImagePreprocessor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        options = self.options
        self.search_region = float(
            options.get("searchRegion", DEFAULT_CORNER_SEARCH_REGION)
        )
        self.mark_size_range = tuple(
            float(x) for x in options.get("markSizeRange", DEFAULT_CORNER_MARK_SIZE_RANGE)
        )

    def apply_filter(self, image, file_path):
        config = self.tuning_config
        marks = self.find_corner_marks(image, file_path)
        if marks is None:
            return None

        logger.info(f"Found corner marks: \t {np.round(marks).astype(int).tolist()}")

        if config.outputs.show_image_level >= 4:
            marked = image.copy()
            for x, y in marks:
                cv2.circle(marked, (int(x), int(y)), 8, 0, 2)
            InteractionUtils.show("Corner marks", marked, config=config)

        return ImageUtils.four_point_transform(image, marks)

    def find_corner_marks(self, image, file_path):
        h, w = image.shape[:2]
        blurred = cv2.GaussianBlur(image, (5, 5), 0)
        _ret, binary = cv2.threshold(
            blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
        )
        contours = ImageUtils.grab_contours(
            cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        )

        page_corners = [(0, 0), (w, 0), (w, h), (0, h)]
        best = [None] * 4
        for contour in contours:
            centre = self.mark_centre(contour, w, h)
            if centre is None:
                continue
            for i, (corner_x, corner_y) in enumerate(page_corners):
                in_region = (
                    abs(centre[0] - corner_x) < self.search_region * w
                    and abs(centre[1] - corner_y) < self.search_region * h
                )
                if not in_region:
                    continue
                # The marks are the outermost print on the sheet, so anything
                # else that passes the shape test (QR code parts, bubbles) is
                # further from the page corner
                distance = np.hypot(centre[0] - corner_x, centre[1] - corner_y)
                if best[i] is None or distance < best[i][0]:
                    best[i] = (distance, centre)

        missing = [name for name, found in zip(CORNER_NAMES, best) if found is None]
        if missing:
            logger.error(
                f"\tError: Corner marks not found for: '{file_path}' ({', '.join(missing)}). "
                "Was the sheet cut off while scanning?"
            )
            return None

        marks = np.array([centre for _distance, centre in best], dtype="float32")
        if not self.is_plausible_frame(marks):
            logger.error(
                f"\tError: Corner marks of '{file_path}' do not form a rectangle: {marks.tolist()}"
            )
            return None
        return marks

    def mark_centre(self, contour, w, h):
        """Centroid of `contour` if it looks like a corner mark, else None.

        The centroid is used instead of the L's outer corner because it barely
        moves when ink spread or blur makes the mark thicker or thinner.
        """
        x, y, cw, ch = cv2.boundingRect(contour)
        # Scanner shadows along the edges are not marks
        if x <= 1 or y <= 1 or x + cw >= w - 1 or y + ch >= h - 1:
            return None
        min_size, max_size = (r * w for r in self.mark_size_range)
        if not (min_size <= cw <= max_size and min_size <= ch <= max_size):
            return None
        if max(cw, ch) / min(cw, ch) > CORNER_MARK_MAX_ASPECT_RATIO:
            return None
        area = cv2.contourArea(contour)
        hull_area = cv2.contourArea(cv2.convexHull(contour))
        if hull_area == 0:
            return None
        min_solidity, max_solidity = CORNER_MARK_SOLIDITY_RANGE
        if not min_solidity <= area / hull_area <= max_solidity:
            return None
        moments = cv2.moments(contour)
        if moments["m00"] == 0:
            return None
        return (moments["m10"] / moments["m00"], moments["m01"] / moments["m00"])

    @staticmethod
    def is_plausible_frame(marks):
        tl, tr, br, bl = marks
        top, bottom = np.linalg.norm(tr - tl), np.linalg.norm(br - bl)
        left, right = np.linalg.norm(bl - tl), np.linalg.norm(br - tr)
        return (
            abs(top - bottom) <= CORNER_MARK_MAX_SIDE_MISMATCH * max(top, bottom)
            and abs(left - right) <= CORNER_MARK_MAX_SIDE_MISMATCH * max(left, right)
        )
