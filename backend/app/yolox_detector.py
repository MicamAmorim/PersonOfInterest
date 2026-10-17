from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort


class YoloXPersonDetector:
    """CPU-friendly YOLOX detector that returns only COCO class 0 (person).

    `confidence` is the normal/high threshold used to create new tracks.
    `low_confidence` is only exposed so the tracker can maintain an existing
    identity through motion blur or partial occlusion. The tracker decides
    whether a returned low-confidence detection may be used.
    """

    def __init__(
        self,
        model_path: str | Path,
        confidence: float = 0.42,
        nms_threshold: float = 0.45,
        low_confidence: float = 0.20,
    ) -> None:
        self.model_path = Path(model_path)
        if not self.model_path.is_file():
            raise FileNotFoundError(f"Modelo YOLOX não encontrado: {self.model_path}")
        self.confidence = float(confidence)
        self.low_confidence = min(float(low_confidence), self.confidence)
        self.nms_threshold = float(nms_threshold)

        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            str(self.model_path),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self.input_name = self.session.get_inputs()[0].name
        shape = self.session.get_inputs()[0].shape
        self.input_h = int(shape[2]) if isinstance(shape[2], int) else 416
        self.input_w = int(shape[3]) if isinstance(shape[3], int) else 416
        self._grids, self._expanded_strides = self._make_grids(self.input_h, self.input_w)

    @staticmethod
    def _make_grids(height: int, width: int) -> tuple[np.ndarray, np.ndarray]:
        grids: list[np.ndarray] = []
        expanded: list[np.ndarray] = []
        for stride in (8, 16, 32):
            hsize, wsize = height // stride, width // stride
            xv, yv = np.meshgrid(np.arange(wsize), np.arange(hsize))
            grid = np.stack((xv, yv), axis=2).reshape(1, -1, 2)
            grids.append(grid)
            expanded.append(np.full((*grid.shape[:2], 1), stride))
        return np.concatenate(grids, axis=1).astype(np.float32), np.concatenate(expanded, axis=1).astype(np.float32)

    def _preprocess(self, image: Any) -> tuple[np.ndarray, float]:
        import cv2

        h, w = image.shape[:2]
        ratio = min(self.input_h / h, self.input_w / w)
        resized = cv2.resize(image, (int(w * ratio), int(h * ratio)), interpolation=cv2.INTER_LINEAR)
        padded = np.full((self.input_h, self.input_w, 3), 114, dtype=np.uint8)
        padded[: resized.shape[0], : resized.shape[1]] = resized
        tensor = padded.transpose(2, 0, 1).astype(np.float32)
        return np.ascontiguousarray(tensor[None, ...]), ratio

    def _decode(self, output: np.ndarray) -> np.ndarray:
        pred = output.copy()
        pred[..., :2] = (pred[..., :2] + self._grids) * self._expanded_strides
        pred[..., 2:4] = np.exp(pred[..., 2:4]) * self._expanded_strides
        return pred

    @staticmethod
    def _nms(boxes: np.ndarray, scores: np.ndarray, threshold: float) -> list[int]:
        if len(boxes) == 0:
            return []
        x1, y1, x2, y2 = boxes.T
        areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
        order = scores.argsort()[::-1]
        keep: list[int] = []
        while order.size > 0:
            i = int(order[0])
            keep.append(i)
            if order.size == 1:
                break
            rest = order[1:]
            xx1 = np.maximum(x1[i], x1[rest])
            yy1 = np.maximum(y1[i], y1[rest])
            xx2 = np.minimum(x2[i], x2[rest])
            yy2 = np.minimum(y2[i], y2[rest])
            inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
            union = areas[i] + areas[rest] - inter
            iou = np.divide(inter, union, out=np.zeros_like(inter), where=union > 0)
            order = rest[iou <= threshold]
        return keep

    def detect(self, frame: Any) -> list[tuple[tuple[int, int, int, int], float]]:
        tensor, ratio = self._preprocess(frame)
        raw = self.session.run(None, {self.input_name: tensor})[0]
        predictions = self._decode(raw)[0]

        person_scores = predictions[:, 4] * predictions[:, 5]
        mask = person_scores >= self.low_confidence
        if not np.any(mask):
            return []

        boxes = predictions[mask, :4]
        scores = person_scores[mask]
        xyxy = np.empty_like(boxes)
        xyxy[:, 0] = boxes[:, 0] - boxes[:, 2] / 2.0
        xyxy[:, 1] = boxes[:, 1] - boxes[:, 3] / 2.0
        xyxy[:, 2] = boxes[:, 0] + boxes[:, 2] / 2.0
        xyxy[:, 3] = boxes[:, 1] + boxes[:, 3] / 2.0
        xyxy /= max(ratio, 1e-6)

        height, width = frame.shape[:2]
        xyxy[:, 0::2] = np.clip(xyxy[:, 0::2], 0, width - 1)
        xyxy[:, 1::2] = np.clip(xyxy[:, 1::2], 0, height - 1)

        detections: list[tuple[tuple[int, int, int, int], float]] = []
        for idx in self._nms(xyxy, scores, self.nms_threshold):
            x1, y1, x2, y2 = xyxy[idx]
            w, h = x2 - x1, y2 - y1
            if w < 12 or h < 24:
                continue
            detections.append(((int(round(x1)), int(round(y1)), int(round(w)), int(round(h))), float(scores[idx])))
        return detections
