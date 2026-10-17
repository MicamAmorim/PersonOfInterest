from __future__ import annotations

from typing import Any

from . import body_identity as bi


def install() -> None:
    """Patch OSNet runtime quirks without changing identity semantics.

    The distributed OSNet x0.25 ONNX model currently used by PersonOfInterest
    has a fixed batch dimension of 16. Identity work is event-oriented, so the
    application normally embeds one crop at a time. Repeat that crop to satisfy
    the fixed batch and keep only the first output vector.

    False-positive review is deliberately fail-safe: a user decision must never
    return HTTP 500 only because optional hard-negative extraction failed.
    """
    cls = bi.BodyIdentityManager
    if getattr(cls, "_poi_fixed_batch_patch", False):
        return

    original_ensure_model = cls._ensure_model
    original_record_false_positive = cls.record_false_positive

    def ensure_model(self: Any) -> None:
        original_ensure_model(self)
        meta = self._session.get_inputs()[0]
        shape = list(meta.shape)
        batch = shape[0] if shape else 1
        try:
            batch = int(batch)
        except (TypeError, ValueError):
            batch = 1
        self._poi_input_batch = max(1, batch)

    def embed_crop(self: Any, crop: Any) -> Any:
        self._ensure_model()
        image = bi.cv2.resize(crop, (128, 256), interpolation=bi.cv2.INTER_LINEAR)
        image = bi.cv2.cvtColor(image, bi.cv2.COLOR_BGR2RGB).astype(bi.np.float32) / 255.0
        mean = bi.np.asarray([0.485, 0.456, 0.406], dtype=bi.np.float32)
        std = bi.np.asarray([0.229, 0.224, 0.225], dtype=bi.np.float32)
        image = (image - mean) / std
        if self._nchw:
            tensor = bi.np.transpose(image, (2, 0, 1))[None, ...]
        else:
            tensor = image[None, ...]

        batch = max(1, int(getattr(self, "_poi_input_batch", 1)))
        if batch > 1:
            tensor = bi.np.repeat(tensor, batch, axis=0)

        output = bi.np.asarray(self._session.run(None, {self._input_name: tensor})[0])
        # Fixed-batch exports usually return [N, embedding_dim]. All repeated
        # rows represent the same crop; retain exactly one embedding.
        if output.ndim >= 2 and output.shape[0] == batch:
            output = output[0]
        return bi._normalize(output)

    def record_false_positive(self: Any, event_id: int) -> None:
        try:
            original_record_false_positive(self, event_id)
            return
        except Exception as exc:
            # The API has already persisted identity_state=false_positive before
            # reaching this optional ReID bookkeeping. Never undo/reject the
            # user's review because an embedding model failed.
            self.error = f"Hard-negative opcional não extraído: {exc}"

        try:
            with bi.connection() as conn:
                # Neutralize any previous positive body evidence from this event
                # so it cannot remain in the verified ReID gallery.
                conn.execute(
                    """UPDATE body_samples
                    SET person_id = NULL, verified = 0, source = 'false_positive', updated_at = ?
                    WHERE event_id = ?""",
                    (bi.utc_now(), event_id),
                )
                conn.execute(
                    """UPDATE events
                    SET probable_person_id = NULL, body_confidence = NULL, body_identity_source = NULL
                    WHERE id = ?""",
                    (event_id,),
                )
                conn.commit()
        except Exception:
            # The authoritative false-positive flag lives on events and was
            # already written by api_v34. ReID cleanup is best effort.
            pass
        self.notify_change()

    cls._ensure_model = ensure_model
    cls._embed_crop = embed_crop
    cls.record_false_positive = record_false_positive
    cls._poi_fixed_batch_patch = True
