"""IOS orientation entrypoint using a trained dental_pose_net checkpoint."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import trimesh


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_output_manifest(output_manifest_path: str, outputs: Dict[str, Any]) -> None:
    Path(output_manifest_path).write_text(
        json.dumps({"version": 1, "outputs": outputs}, indent=2) + "\n",
        encoding="utf-8",
    )


class PointNetEncoder(nn.Module):
    def __init__(self, feature_dim: int = 256) -> None:
        super().__init__()
        self.mlp = nn.Sequential(
            nn.Conv1d(3, 64, kernel_size=1),
            nn.BatchNorm1d(64),
            nn.ReLU(inplace=True),
            nn.Conv1d(64, 128, kernel_size=1),
            nn.BatchNorm1d(128),
            nn.ReLU(inplace=True),
            nn.Conv1d(128, feature_dim, kernel_size=1),
            nn.BatchNorm1d(feature_dim),
            nn.ReLU(inplace=True),
        )

    def forward(self, points: torch.Tensor) -> torch.Tensor:
        x = points.transpose(1, 2)
        x = self.mlp(x)
        return torch.max(x, dim=2).values


def rot6d_to_matrix(rot_6d: torch.Tensor) -> torch.Tensor:
    a1 = rot_6d[..., 0:3]
    a2 = rot_6d[..., 3:6]

    b1 = F.normalize(a1, dim=-1)
    b2 = F.normalize(a2 - (b1 * a2).sum(dim=-1, keepdim=True) * b1, dim=-1)
    b3 = torch.cross(b1, b2, dim=-1)
    return torch.stack((b1, b2, b3), dim=-1)


class PairPointNetRot6D(nn.Module):
    def __init__(self, feature_dim: int = 256, head_hidden_dim: int = 256) -> None:
        super().__init__()
        self.encoder = PointNetEncoder(feature_dim=feature_dim)
        self.head = nn.Sequential(
            nn.Linear(feature_dim * 2, head_hidden_dim),
            nn.ReLU(inplace=True),
            nn.Linear(head_hidden_dim, 128),
            nn.ReLU(inplace=True),
            nn.Linear(128, 6),
        )

    def forward(
        self, upper_points: torch.Tensor, lower_points: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        upper_feat = self.encoder(upper_points)
        lower_feat = self.encoder(lower_points)
        fused = torch.cat([upper_feat, lower_feat], dim=1)
        pred_rot6d = self.head(fused)
        pred_rotation = rot6d_to_matrix(pred_rot6d)
        return pred_rot6d, pred_rotation


def _load_mesh(path: str) -> trimesh.Trimesh:
    mesh_data = trimesh.load(path, process=False, force="mesh")
    if isinstance(mesh_data, trimesh.Scene):
        if not mesh_data.geometry:
            raise SystemExit(f"Scene has no geometry: {path}")
        mesh = trimesh.util.concatenate(tuple(mesh_data.geometry.values()))
    else:
        mesh = mesh_data
    if not isinstance(mesh, trimesh.Trimesh):
        raise SystemExit(f"Failed to load mesh from {path}")
    return mesh


def _sample_points_from_mesh(
    mesh: trimesh.Trimesh,
    num_points: int,
    rng: np.random.Generator,
) -> np.ndarray:
    vertices = np.asarray(mesh.vertices, dtype=np.float32)
    if vertices.shape[0] == 0:
        raise SystemExit("Mesh has no vertices")

    faces = (
        np.asarray(mesh.faces, dtype=np.int64)
        if mesh.faces is not None
        else np.empty((0, 3), dtype=np.int64)
    )
    if faces.shape[0] == 0:
        replace = vertices.shape[0] < num_points
        idx = rng.choice(vertices.shape[0], size=num_points, replace=replace)
        return vertices[idx].astype(np.float32)

    triangles = vertices[faces]
    vec0 = triangles[:, 1, :] - triangles[:, 0, :]
    vec1 = triangles[:, 2, :] - triangles[:, 0, :]
    face_areas = 0.5 * np.linalg.norm(np.cross(vec0, vec1), axis=1)

    total_area = float(face_areas.sum())
    if total_area <= 1e-12 or not np.isfinite(total_area):
        replace = vertices.shape[0] < num_points
        idx = rng.choice(vertices.shape[0], size=num_points, replace=replace)
        return vertices[idx].astype(np.float32)

    probs = face_areas / total_area
    chosen_faces = rng.choice(faces.shape[0], size=num_points, p=probs)
    tris = triangles[chosen_faces]

    u = rng.random(num_points)
    v = rng.random(num_points)
    sqrt_u = np.sqrt(u)

    w0 = 1.0 - sqrt_u
    w1 = sqrt_u * (1.0 - v)
    w2 = sqrt_u * v

    samples = (
        w0[:, None] * tris[:, 0, :]
        + w1[:, None] * tris[:, 1, :]
        + w2[:, None] * tris[:, 2, :]
    )
    return samples.astype(np.float32)


def _joint_normalize_pair(
    upper_points: np.ndarray,
    lower_points: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    all_points = np.concatenate([upper_points, lower_points], axis=0)
    center = all_points.mean(axis=0)
    centered = all_points - center
    scale = float(np.linalg.norm(centered, axis=1).max())
    if scale < 1e-8:
        scale = 1.0
    upper_norm = (upper_points - center) / scale
    lower_norm = (lower_points - center) / scale
    return upper_norm.astype(np.float32), lower_norm.astype(np.float32)


def _apply_rotation_to_mesh_about_center(
    mesh: trimesh.Trimesh,
    rotation: np.ndarray,
    center: np.ndarray,
) -> trimesh.Trimesh:
    transform = np.eye(4, dtype=np.float64)
    transform[:3, :3] = rotation.astype(np.float64)

    center64 = center.astype(np.float64)
    transform[:3, 3] = center64 - transform[:3, :3] @ center64

    out = mesh.copy()
    out.apply_transform(transform)
    return out


def _save_mesh(mesh: trimesh.Trimesh, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(path)


def _resolve_upper_lower_inputs(inputs: Dict[str, str]) -> Tuple[str, str]:
    if "upper" in inputs and "lower" in inputs:
        return str(inputs["upper"]), str(inputs["lower"])

    upper_candidate: str | None = None
    lower_candidate: str | None = None
    for _, path in inputs.items():
        p = str(path)
        name = Path(p).name.lower()
        if upper_candidate is None and "upper" in name:
            upper_candidate = p
        if lower_candidate is None and "lower" in name:
            lower_candidate = p
    if upper_candidate and lower_candidate:
        return upper_candidate, lower_candidate

    items = sorted(inputs.items(), key=lambda kv: kv[0])
    if len(items) < 2:
        raise SystemExit("Input manifest must provide upper and lower IOS meshes")
    return str(items[0][1]), str(items[1][1])


def _run_orientation(
    *,
    checkpoint_path: Path,
    upper_path: str,
    lower_path: str,
    output_dir: Path,
    num_points_upper: int,
    num_points_lower: int,
    seed: int,
) -> Dict[str, Path]:
    if not checkpoint_path.exists():
        raise SystemExit(f"Checkpoint not found: {checkpoint_path}")

    checkpoint = torch.load(str(checkpoint_path), map_location="cpu")
    train_cfg = checkpoint.get("config", {})
    feature_dim = int(train_cfg.get("feature_dim", 256))
    head_hidden_dim = int(train_cfg.get("head_hidden_dim", 256))

    model = PairPointNetRot6D(feature_dim=feature_dim, head_hidden_dim=head_hidden_dim)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    upper_mesh = _load_mesh(upper_path)
    lower_mesh = _load_mesh(lower_path)
    center = np.concatenate(
        [
            np.asarray(upper_mesh.vertices, dtype=np.float32),
            np.asarray(lower_mesh.vertices, dtype=np.float32),
        ],
        axis=0,
    ).mean(axis=0)

    rng = np.random.default_rng(seed)
    upper_points = _sample_points_from_mesh(upper_mesh, num_points_upper, rng)
    lower_points = _sample_points_from_mesh(lower_mesh, num_points_lower, rng)
    upper_points, lower_points = _joint_normalize_pair(upper_points, lower_points)

    upper_tensor = torch.from_numpy(upper_points).unsqueeze(0)
    lower_tensor = torch.from_numpy(lower_points).unsqueeze(0)

    with torch.no_grad():
        _, pred_rotation = model(upper_tensor, lower_tensor)
    rotation = pred_rotation[0].cpu().numpy().astype(np.float32)

    rotated_upper = _apply_rotation_to_mesh_about_center(upper_mesh, rotation, center)
    rotated_lower = _apply_rotation_to_mesh_about_center(lower_mesh, rotation, center)

    upper_out = output_dir / "upper_rotated.stl"
    lower_out = output_dir / "lower_rotated.stl"
    _save_mesh(rotated_upper, upper_out)
    _save_mesh(rotated_lower, lower_out)

    return {"upper": upper_out, "lower": lower_out}


def main() -> int:
    input_manifest_path = _require_env("TF_INPUT_MANIFEST")
    output_manifest_path = _require_env("TF_OUTPUT_MANIFEST")

    manifest_raw = _read_json(input_manifest_path)
    inputs = manifest_raw["inputs"]
    if not isinstance(inputs, dict):
        raise SystemExit("Input manifest field 'inputs' must be an object")

    out_manifest_file = Path(output_manifest_path)
    output_dir = out_manifest_file.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    checkpoint_path = Path(
        os.environ.get("IOS_ORIENTER_CHECKPOINT", "/app/checkpoints/best.pt")
    )
    num_points_upper = int(os.environ.get("IOS_ORIENTER_NUM_POINTS_UPPER", "2056"))
    num_points_lower = int(os.environ.get("IOS_ORIENTER_NUM_POINTS_LOWER", "2056"))
    seed = int(os.environ.get("IOS_ORIENTER_SEED", "123"))

    upper_path, lower_path = _resolve_upper_lower_inputs(inputs)

    produced = _run_orientation(
        checkpoint_path=checkpoint_path,
        upper_path=upper_path,
        lower_path=lower_path,
        output_dir=output_dir,
        num_points_upper=num_points_upper,
        num_points_lower=num_points_lower,
        seed=seed,
    )

    outputs: Dict[str, Any] = {}
    for logical_name, out_path in produced.items():
        outputs[str(logical_name)] = {
            "path": out_path.name,
            "content_type": "model/stl",
        }

    _write_output_manifest(output_manifest_path, outputs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
