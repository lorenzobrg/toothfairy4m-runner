"""Bite classification entrypoint based on Bits2Bites/PT-v3."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import numpy as np
import torch
import trimesh


MODEL_CHECKPOINT_PATH = Path(os.getenv("BITE_MODEL_PATH", "/app/models/model_best.pth"))
OUTPUT_FILENAME = os.getenv(
    "BITE_OUTPUT_FILENAME", "ios_bite_classification_results.json"
)
TARGET_POINTS = int(os.getenv("BITE_TARGET_POINTS", "16384"))
GRID_SIZE = float(os.getenv("BITE_GRID_SIZE", "0.01"))

SAGITTAL_LABELS = ["I", "II_full", "III"]
VERTICAL_LABELS = ["normal", "deep", "open", "reverse"]
TRANSVERSE_LABELS = ["normal", "scissor", "cross"]
MIDLINE_LABELS = ["centered", "deviated"]


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _select_device() -> torch.device:
    requested = (os.getenv("BITE_DEVICE") or "auto").strip().lower()
    if requested in {"cuda", "gpu"}:
        if not torch.cuda.is_available():
            raise RuntimeError("BITE_DEVICE requests cuda but no CUDA device is available")
        return torch.device("cuda")
    if requested == "cpu":
        raise RuntimeError(
            "BITE_DEVICE=cpu is not supported by the current spconv-based inference stack"
        )
    if not torch.cuda.is_available():
        raise RuntimeError(
            "No CUDA device detected; this inference stack requires NVIDIA GPU runtime"
        )
    return torch.device("cuda")


def _strip_state_dict_prefixes(state_dict: Dict[str, torch.Tensor]) -> Dict[str, torch.Tensor]:
    cleaned: Dict[str, torch.Tensor] = {}
    for key, value in state_dict.items():
        key_out = key
        if key_out.startswith("module."):
            key_out = key_out[len("module.") :]
        if key_out.startswith("model."):
            key_out = key_out[len("model.") :]
        cleaned[key_out] = value
    return cleaned


def _build_model(device: torch.device) -> torch.nn.Module:
    from pointcept.models.builder import build_model

    # Register only required models for inference.
    import pointcept.models.multi_task_classifier.multi_task_classifier_v1m1_base  # noqa: F401
    import pointcept.models.point_transformer_v3.point_transformer_v3m1_base  # noqa: F401

    model_cfg: Dict[str, Any] = {
        "type": "MultiTaskClassifier",
        "backbone_embed_dim": 128,
        "num_classes_list": [3, 3, 4, 3, 2],
        "class_weights": None,
        "loss_type": "ce",
        "backbone": {
            "type": "PT-v3m1",
            "in_channels": 9,
            "enc_channels": (16, 32, 48, 64, 128),
            "enc_num_head": (1, 2, 3, 4, 8),
            "dec_channels": (32, 32, 64, 96),
            "dec_num_head": (2, 2, 4, 6),
            "enable_flash": False,
            "cls_mode": True,
        },
    }

    model = build_model(model_cfg)
    checkpoint = torch.load(
        str(MODEL_CHECKPOINT_PATH), map_location=device, weights_only=False
    )
    if isinstance(checkpoint, dict) and isinstance(checkpoint.get("state_dict"), dict):
        state_dict = checkpoint["state_dict"]
    elif isinstance(checkpoint, dict) and isinstance(checkpoint.get("model"), dict):
        state_dict = checkpoint["model"]
    elif isinstance(checkpoint, dict):
        state_dict = checkpoint
    else:
        raise RuntimeError("Unsupported checkpoint format")

    cleaned_state = _strip_state_dict_prefixes(state_dict)
    missing, unexpected = model.load_state_dict(cleaned_state, strict=False)
    if unexpected:
        print(f"Warning: ignoring unexpected checkpoint keys: {unexpected}")
    if missing:
        print(f"Warning: missing checkpoint keys: {missing}")

    model.to(device)
    model.eval()
    return model


def _resolve_stl_paths(inputs: Dict[str, str]) -> List[Tuple[str, Path]]:
    stl_items: List[Tuple[str, Path]] = []
    for logical_name, file_path in inputs.items():
        p = Path(file_path)
        if p.name.lower().endswith(".stl"):
            stl_items.append((logical_name, p))
    if not stl_items:
        raise RuntimeError("No STL inputs found in manifest")
    return stl_items


def _ordered_stl_paths(stl_items: Sequence[Tuple[str, Path]]) -> List[Path]:
    keyed = [(name.lower(), path) for name, path in stl_items]
    ordered: List[Path] = []

    for needle in ("upper", "maxillary"):
        for key, path in keyed:
            if needle in key and path not in ordered:
                ordered.append(path)
                break

    for needle in ("lower", "mandibular"):
        for key, path in keyed:
            if needle in key and path not in ordered:
                ordered.append(path)
                break

    for _, path in keyed:
        if path not in ordered:
            ordered.append(path)

    return ordered[:2]


def _resample_points(points: np.ndarray, target_count: int) -> np.ndarray:
    if points.shape[0] == 0:
        raise RuntimeError("Empty point cloud")

    if points.shape[0] >= target_count:
        idx = np.random.choice(points.shape[0], size=target_count, replace=False)
    else:
        idx = np.random.choice(points.shape[0], size=target_count, replace=True)
    return points[idx].astype(np.float32, copy=False)


def _sample_mesh_points(mesh_path: Path, target_count: int) -> np.ndarray:
    loaded = trimesh.load(str(mesh_path), process=False)

    if isinstance(loaded, trimesh.Scene):
        geometries = [g for g in loaded.geometry.values() if isinstance(g, trimesh.Trimesh)]
        if not geometries:
            raise RuntimeError(f"No mesh geometry found in {mesh_path}")
        mesh = trimesh.util.concatenate(geometries)
    elif isinstance(loaded, trimesh.Trimesh):
        mesh = loaded
    else:
        raise RuntimeError(f"Unsupported mesh type for {mesh_path}")

    if mesh.vertices is None or len(mesh.vertices) == 0:
        raise RuntimeError(f"Mesh {mesh_path} has no vertices")

    if mesh.faces is None or len(mesh.faces) == 0:
        return _resample_points(np.asarray(mesh.vertices, dtype=np.float32), target_count)

    sampled_points, _ = trimesh.sample.sample_surface(mesh, target_count)
    return sampled_points.astype(np.float32, copy=False)


def _normalize_coords(coords: np.ndarray) -> np.ndarray:
    centroid = np.mean(coords, axis=0)
    centered = coords - centroid
    scale = float(np.max(np.linalg.norm(centered, axis=1)))
    if scale > 1e-8:
        centered = centered / scale
    return centered.astype(np.float32, copy=False)


def _grid_sample(coords: np.ndarray, grid_size: float) -> Tuple[np.ndarray, np.ndarray]:
    if coords.shape[0] == 0:
        raise RuntimeError("Cannot grid-sample an empty point cloud")

    coord_min = coords.min(axis=0, keepdims=True)
    grid_coord = np.floor((coords - coord_min) / grid_size).astype(np.int32)

    _, unique_idx = np.unique(grid_coord, axis=0, return_index=True)
    unique_idx = np.sort(unique_idx)
    return coords[unique_idx], grid_coord[unique_idx]


def _prepare_point_tensor_inputs(stl_paths: Sequence[Path]) -> Dict[str, torch.Tensor]:
    points_per_mesh = max(TARGET_POINTS // max(len(stl_paths), 1), 2048)
    sampled_parts = [_sample_mesh_points(path, points_per_mesh) for path in stl_paths]
    coords = np.concatenate(sampled_parts, axis=0).astype(np.float32, copy=False)

    coords = _normalize_coords(coords)
    coords, grid_coord = _grid_sample(coords, GRID_SIZE)
    coords = _resample_points(coords, TARGET_POINTS)

    coord_min = coords.min(axis=0, keepdims=True)
    grid_coord = np.floor((coords - coord_min) / GRID_SIZE).astype(np.int32)

    one_hot = np.zeros((coords.shape[0], 6), dtype=np.float32)
    feat = np.concatenate([coords, one_hot], axis=1)

    return {
        "coord": torch.from_numpy(coords).float(),
        "grid_coord": torch.from_numpy(grid_coord).int(),
        "feat": torch.from_numpy(feat).float(),
        "offset": torch.tensor([coords.shape[0]], dtype=torch.long),
    }


def _safe_label(label_list: Sequence[str], index: int) -> str:
    if 0 <= index < len(label_list):
        return label_list[index]
    return "Unknown"


def _run_inference(
    model: torch.nn.Module,
    batch_inputs: Dict[str, torch.Tensor],
    device: torch.device,
) -> Tuple[Dict[str, str], Dict[str, Dict[str, Any]]]:
    batch = {k: v.to(device) for k, v in batch_inputs.items()}

    with torch.no_grad():
        output = model(batch)
    logits = output["logits"]
    if len(logits) != 5:
        raise RuntimeError(f"Expected 5 logits heads, found {len(logits)}")

    predictions = [int(torch.argmax(head, dim=1).item()) for head in logits]
    probabilities = [
        torch.softmax(head, dim=1).squeeze(0).detach().cpu().tolist() for head in logits
    ]

    classification = {
        "sagittal_right": _safe_label(SAGITTAL_LABELS, predictions[0]),
        "sagittal_left": _safe_label(SAGITTAL_LABELS, predictions[1]),
        "vertical": _safe_label(VERTICAL_LABELS, predictions[2]),
        "transverse": _safe_label(TRANSVERSE_LABELS, predictions[3]),
        "midline": _safe_label(MIDLINE_LABELS, predictions[4]),
    }

    details = {
        "label_0_right": {"pred": predictions[0], "probabilities": probabilities[0]},
        "label_1_left": {"pred": predictions[1], "probabilities": probabilities[1]},
        "label_2_vertical": {"pred": predictions[2], "probabilities": probabilities[2]},
        "label_3_transverse": {
            "pred": predictions[3],
            "probabilities": probabilities[3],
        },
        "label_4_midline": {"pred": predictions[4], "probabilities": probabilities[4]},
    }
    return classification, details


def _find_input_manifest_paths(manifest_inputs: Dict[str, str]) -> List[Path]:
    stl_items = _resolve_stl_paths(manifest_inputs)
    ordered_paths = _ordered_stl_paths(stl_items)
    existing = [p for p in ordered_paths if p.exists()]
    if not existing:
        raise RuntimeError("None of the STL inputs exist inside the container")
    return existing


def main() -> int:
    np.random.seed(42)
    torch.manual_seed(42)

    input_manifest_path = Path(_require_env("TF_INPUT_MANIFEST"))
    output_manifest_path = Path(_require_env("TF_OUTPUT_MANIFEST"))

    if not MODEL_CHECKPOINT_PATH.exists():
        raise RuntimeError(f"Checkpoint not found: {MODEL_CHECKPOINT_PATH}")

    manifest_raw = _read_json(input_manifest_path)
    inputs = manifest_raw.get("inputs")
    if not isinstance(inputs, dict):
        raise RuntimeError("Input manifest must contain an 'inputs' object")

    stl_paths = _find_input_manifest_paths(inputs)
    point_inputs = _prepare_point_tensor_inputs(stl_paths)

    device = _select_device()
    model = _build_model(device)
    classification, details = _run_inference(model, point_inputs, device)

    output_dir = output_manifest_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    result_payload = {
        **classification,
        "raw": details,
        "meta": {
            "input_files": [str(p) for p in stl_paths],
            "device": str(device),
            "checkpoint": str(MODEL_CHECKPOINT_PATH),
            "target_points": TARGET_POINTS,
            "grid_size": GRID_SIZE,
        },
    }

    result_path = output_dir / OUTPUT_FILENAME
    _write_json(result_path, result_payload)

    output_manifest = {
        "version": 1,
        "outputs": {
            "bite_classification_results": {
                "path": result_path.name,
                "content_type": "application/json",
            }
        },
    }
    _write_json(output_manifest_path, output_manifest)

    print(json.dumps({"status": "ok", "result": classification}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
