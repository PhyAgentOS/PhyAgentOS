"""LocateAnything 2D proposal worker for its dedicated model environment."""

from __future__ import annotations

import argparse
import contextlib
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping

from worker_protocol import serve

_BOX = re.compile(r"<box>\s*(.*?)\s*</box>", re.IGNORECASE | re.DOTALL)
_COORD = re.compile(r"<\s*(\d+)\s*>|(\d+)")


class LocateAnythingProposalWorker:
    def __init__(
        self,
        *,
        model_id: str,
        revision: str,
        device: str,
        cache_dir: Path,
        modules_cache_dir: Path,
        generation_mode: str,
        max_new_tokens: int,
        repetition_penalty: float,
        temperature: float,
        top_p: float,
        decode_seed: int,
        local_files_only: bool,
    ) -> None:
        if generation_mode not in {"fast", "hybrid"}:
            raise ValueError("generation_mode must be fast or hybrid")
        if max_new_tokens < 1 or decode_seed < 0:
            raise ValueError("generation limits are invalid")
        if repetition_penalty < 1 or temperature <= 0 or not 0 < top_p <= 1:
            raise ValueError("generation sampling parameters are invalid")
        self.model_id = model_id
        self.revision = revision
        self.device = device
        self.cache_dir = cache_dir
        self.modules_cache_dir = modules_cache_dir
        self.generation_mode = generation_mode
        self.max_new_tokens = max_new_tokens
        self.repetition_penalty = repetition_penalty
        self.temperature = temperature
        self.top_p = top_p
        self.decode_seed = decode_seed
        self.local_files_only = local_files_only
        self._tokenizer: Any = None
        self._processor: Any = None
        self._model: Any = None

    def load(self) -> None:
        if self._model is not None:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.modules_cache_dir.mkdir(parents=True, exist_ok=True)
        os.environ["HF_MODULES_CACHE"] = str(self.modules_cache_dir)
        with contextlib.redirect_stdout(sys.stderr):
            import torch
            from transformers import AutoModel, AutoProcessor, AutoTokenizer

            if self.device.startswith("cuda") and not torch.cuda.is_available():
                raise RuntimeError("configured CUDA device is unavailable")
            common = {
                "revision": self.revision,
                "cache_dir": str(self.cache_dir),
                "trust_remote_code": True,
                "local_files_only": self.local_files_only,
            }
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_id, **common)
            self._processor = AutoProcessor.from_pretrained(self.model_id, **common)
            dtype = torch.bfloat16 if self.device.startswith("cuda") else torch.float32
            self._model = AutoModel.from_pretrained(
                self.model_id,
                torch_dtype=dtype,
                **common,
            ).to(self.device).eval()

    def handle(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        request_id = request["request_id"]
        if set(request) != {
            "request_id", "operation", "observation_ref", "scene_revision",
            "entity_ref", "query", "rgb_path", "image_size_px",
        } or request.get("operation") != "propose_2d_boxes":
            return {"request_id": request_id, "status": "unavailable", "proposals": []}
        try:
            from PIL import Image

            rgb_path = _absolute_file(request.get("rgb_path"))
            expected_size = _image_size(request.get("image_size_px"))
            with Image.open(rgb_path) as source:
                image = source.convert("RGB")
            if image.size != expected_size:
                raise ValueError("RGB dimensions do not match request")
            answer = self._generate(image, _text(request.get("query"), "query"))
            boxes = _parse_boxes(answer, *expected_size)
            return {
                "request_id": request_id,
                "status": "available" if boxes else "empty",
                "proposals": [
                    {"bbox_xyxy_px": list(box), "confidence": None} for box in boxes
                ],
            }
        except Exception as exc:
            print(f"LocateAnything inference failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return {"request_id": request_id, "status": "unavailable", "proposals": []}

    def _generate(self, image: Any, query: str) -> str:
        import torch

        prompt = f"Locate all the instances that match the following description: {query}."
        messages = [{"role": "user", "content": [
            {"type": "image", "image": image},
            {"type": "text", "text": prompt},
        ]}]
        processor, model = self._processor, self._model
        with contextlib.redirect_stdout(sys.stderr):
            text = processor.py_apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            images, videos = processor.process_vision_info(messages)
            inputs = processor(text=[text], images=images, videos=videos, return_tensors="pt").to(self.device)
            torch.manual_seed(self.decode_seed)
            if self.device.startswith("cuda"):
                torch.cuda.manual_seed_all(self.decode_seed)
            with torch.no_grad():
                result = model.generate(
                    pixel_values=inputs["pixel_values"].to(model.dtype),
                    input_ids=inputs["input_ids"],
                    attention_mask=inputs["attention_mask"],
                    image_grid_hws=inputs.get("image_grid_hws"),
                    tokenizer=self._tokenizer,
                    max_new_tokens=self.max_new_tokens,
                    use_cache=True,
                    generation_mode=self.generation_mode,
                    do_sample=True,
                    temperature=self.temperature,
                    top_p=self.top_p,
                    repetition_penalty=self.repetition_penalty,
                    verbose=False,
                )
        answer = result[0] if isinstance(result, tuple) else result
        if isinstance(answer, (list, tuple)) and len(answer) == 1:
            answer = answer[0]
        if not isinstance(answer, str):
            raise TypeError("model generation did not return text")
        return answer


def _parse_boxes(answer: str, width: int, height: int) -> tuple[tuple[int, int, int, int], ...]:
    blocks = _BOX.findall(answer)
    if not blocks:
        raise ValueError("model response contains no explicit box result")
    if any(block.strip().casefold() == "none" for block in blocks):
        if len(blocks) != 1:
            raise ValueError("model response mixes none and boxes")
        return ()
    boxes = []
    for block in blocks:
        values = [next(item for item in match.groups() if item is not None) for match in _COORD.finditer(block)]
        remainder = _COORD.sub("", block)
        if len(values) != 4 or remainder.strip(" ,\t\r\n"):
            raise ValueError("model response box syntax is invalid")
        normalized = tuple(int(item) for item in values)
        if any(item < 0 or item > 1000 for item in normalized):
            raise ValueError("normalized box is outside [0, 1000]")
        x1, y1, x2, y2 = normalized
        box = (
            max(0, min(width - 1, round(x1 * width / 1000))),
            max(0, min(height - 1, round(y1 * height / 1000))),
            max(1, min(width, round(x2 * width / 1000))),
            max(1, min(height, round(y2 * height / 1000))),
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            raise ValueError("model response box is degenerate")
        boxes.append(box)
    return tuple(boxes)


def _absolute_file(value: Any) -> Path:
    path = Path(value) if isinstance(value, str) else Path()
    if not path.is_absolute() or not path.is_file():
        raise ValueError("rgb_path must be an existing absolute file")
    return path.resolve()


def _image_size(value: Any) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2 or any(
        isinstance(item, bool) or not isinstance(item, int) or item < 1 for item in value
    ):
        raise ValueError("image_size_px must contain positive integer width and height")
    return value[0], value[1]


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty")
    return value.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--modules-cache-dir", type=Path, required=True)
    parser.add_argument("--generation-mode", choices=("fast", "hybrid"), default="fast")
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    parser.add_argument("--repetition-penalty", type=float, default=1.1)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--decode-seed", type=int, default=0)
    parser.add_argument("--allow-download", action="store_true")
    args = parser.parse_args()
    numeric = (args.repetition_penalty, args.temperature, args.top_p)
    if any(not math.isfinite(value) for value in numeric):
        parser.error("sampling parameters must be finite")
    worker = LocateAnythingProposalWorker(
        model_id=_text(args.model_id, "model_id"),
        revision=_text(args.revision, "revision"),
        device=_text(args.device, "device"),
        cache_dir=args.cache_dir.expanduser().resolve(),
        modules_cache_dir=args.modules_cache_dir.expanduser().resolve(),
        generation_mode=args.generation_mode,
        max_new_tokens=args.max_new_tokens,
        repetition_penalty=args.repetition_penalty,
        temperature=args.temperature,
        top_p=args.top_p,
        decode_seed=args.decode_seed,
        local_files_only=not args.allow_download,
    )
    return serve("locateanything", worker.load, worker.handle)


if __name__ == "__main__":
    raise SystemExit(main())
