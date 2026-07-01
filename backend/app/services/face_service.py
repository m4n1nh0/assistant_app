import base64
import json
from dataclasses import dataclass

from loguru import logger


@dataclass
class FaceComparison:
    ok: bool
    distance: int
    threshold: int


def enroll_face(image_bytes: bytes) -> str:
    descriptor = _face_descriptor(image_bytes)
    payload = {
        "version": 2,
        "algorithm": "opencv-haar-lbph-lite-8x8",
        "descriptor": descriptor,
    }
    return base64.b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")


def compare_face(reference_template: str, image_bytes: bytes) -> FaceComparison:
    reference = _decode_template(reference_template)
    sample = _face_descriptor(image_bytes)
    distance = _descriptor_distance(reference, sample)
    threshold = 1450
    return FaceComparison(ok=distance <= threshold, distance=distance, threshold=threshold)


def _decode_template(template: str) -> list[int]:
    try:
        raw = base64.b64decode(template.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
        algorithm = payload.get("algorithm")
        if algorithm == "opencv-haar-lbph-lite-8x8":
            return [int(item) for item in payload["descriptor"]]
        if algorithm == "center-ahash-32":
            raise ValueError("template antigo; recadastre o rosto com OpenCV")
        raise ValueError("unsupported face template algorithm")
    except Exception as exc:
        raise ValueError("template facial invalido") from exc


def _face_descriptor(image_bytes: bytes) -> list[int]:
    try:
        import cv2
        import numpy as np

        data = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("imagem facial invalida")

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        face = _detect_largest_face(cv2, gray)
        if face is None:
            raise ValueError("nenhum rosto detectado")

        x, y, w, h = face
        margin_x = int(w * 0.14)
        margin_y = int(h * 0.18)
        left = max(0, x - margin_x)
        top = max(0, y - margin_y)
        right = min(gray.shape[1], x + w + margin_x)
        bottom = min(gray.shape[0], y + h + margin_y)

        roi = gray[top:bottom, left:right]
        roi = cv2.resize(roi, (128, 128), interpolation=cv2.INTER_AREA)
        roi = cv2.GaussianBlur(roi, (3, 3), 0)
        return _lbph_lite_descriptor(cv2, roi)
    except ValueError:
        raise
    except Exception as exc:
        logger.warning(f"OpenCV face processing failed: {exc}")
        raise ValueError("imagem facial invalida") from exc


def _detect_largest_face(cv2, gray):
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(cascade_path)
    if detector.empty():
        raise ValueError("classificador facial OpenCV indisponivel")

    faces = detector.detectMultiScale(
        gray,
        scaleFactor=1.08,
        minNeighbors=5,
        minSize=(64, 64),
        flags=cv2.CASCADE_SCALE_IMAGE,
    )
    if len(faces) == 0:
        return None
    return max(faces, key=lambda item: item[2] * item[3])


def _lbph_lite_descriptor(cv2, roi) -> list[int]:
    descriptor: list[int] = []
    cell_size = 16
    for top in range(0, 128, cell_size):
        for left in range(0, 128, cell_size):
            cell = roi[top:top + cell_size, left:left + cell_size]
            hist = cv2.calcHist([cell], [0], None, [16], [0, 256]).flatten()
            total = max(1.0, float(hist.sum()))
            descriptor.extend(int(round((value / total) * 1000)) for value in hist)
    return descriptor


def _descriptor_distance(a: list[int], b: list[int]) -> int:
    if len(a) != len(b):
        raise ValueError("template facial incompativel")
    return int(sum(abs(x - y) for x, y in zip(a, b)))
