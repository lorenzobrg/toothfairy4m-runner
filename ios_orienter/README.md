# IOS Orienter Runner

This package contains both:

- `entrypoint.py`: algorithm container entrypoint that orients IOS upper/lower meshes.
- `runner/`: Celery external runner that claims ToothFairy4M jobs, stages input files, runs the algorithm container, uploads outputs, and reports completion/failure.

The orientation logic matches `dental_pose_net` inference flow:

- sample points from upper/lower meshes,
- joint normalization,
- predict one rotation matrix with `PairPointNetRot6D`,
- apply that rotation to both meshes about the joint mesh center,
- write only rotated STL outputs (`upper` and `lower`) with no extra report file.

## Checkpoint placement (`best.pt`)

Put the trained checkpoint here before building the image:

- `checkpoints/best.pt`

The Docker image copies this project into `/app` (`COPY . /app`), so inside the container the default checkpoint path is:

- `/app/checkpoints/best.pt`

The algorithm entrypoint reads:

- `IOS_ORIENTER_CHECKPOINT` (default `/app/checkpoints/best.pt`)

If the checkpoint file is changed, rebuild the image.

## Output keys

The algorithm writes this output manifest shape:

```json
{
  "version": 1,
  "outputs": {
    "upper": {"path": "upper_rotated.stl", "content_type": "model/stl"},
    "lower": {"path": "lower_rotated.stl", "content_type": "model/stl"}
  }
}
```

ToothFairy4M maps these keys to `ios_processed_upper` and `ios_processed_lower`.

## Environment

Copy one of the env templates and fill values:

- `.env.example`: direct `docker run` style setup.
- `.env.compose.example`: `docker compose` setup.

Important variables:

- Runner/API/storage: `RUNNER_*`, `CELERY_*`, `OBJECT_STORAGE_*`.
- Algorithm image selection: `ALGORITHM_IMAGE_MAP`.
- Algorithm command: `ALGORITHM_CONTAINER_CMD` (default `python /app/entrypoint.py`).
- IOS orienter runtime: `IOS_ORIENTER_CHECKPOINT`, `IOS_ORIENTER_NUM_POINTS_UPPER`, `IOS_ORIENTER_NUM_POINTS_LOWER`, `IOS_ORIENTER_SEED`.
- Optional env forwarding: `ALGORITHM_ENV_PASSTHROUGH` (comma-separated variable names).

## Build

```bash
docker build -t toothfairy4m-ios_orienter:latest .
```

## Run worker (Docker Compose)

```bash
cp .env.compose.example .env
docker compose up --build -d
```

Useful commands:

```bash
docker compose logs -f runner
docker compose down
```

## Run algorithm only (contract test)

Prepare:

```text
work/
  input/
    manifest.json
    upper.stl
    lower.stl
  output/
```

Example `work/input/manifest.json`:

```json
{
  "version": 1,
  "inputs": {
    "upper": "/work/input/upper.stl",
    "lower": "/work/input/lower.stl"
  }
}
```

Run:

```bash
docker run --rm \
  --entrypoint python \
  -v "$PWD/work:/work" \
  -e TF_INPUT_MANIFEST=/work/input/manifest.json \
  -e TF_OUTPUT_MANIFEST=/work/output/manifest.json \
  toothfairy4m-ios_orienter:latest \
  /app/entrypoint.py
```

Outputs are written to `work/output/`.
