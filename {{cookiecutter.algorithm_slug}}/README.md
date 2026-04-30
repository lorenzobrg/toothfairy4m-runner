# {{ cookiecutter.algorithm_name }}

{{ cookiecutter.algorithm_description }}

This template now scaffolds two pieces:

- `entrypoint.py`: algorithm logic that reads `/work/input` and writes `/work/output`
- `runner/`: external Celery worker that claims jobs from ToothFairy4M API, handles object storage I/O, runs the algorithm container, and reports completion/failure

## Algorithm contract

The external runner provides:

- `TF_INPUT_MANIFEST=/work/input/manifest.json`
- `TF_OUTPUT_MANIFEST=/work/output/manifest.json`

The algorithm container must:

- Read the input manifest JSON
- Write all output files under `/work/output/`
- Write the output manifest JSON to `TF_OUTPUT_MANIFEST`

### Input manifest (keep it simple)

The runner will provide an input manifest JSON. In practice it may contain extra metadata
(like `job`, `modality`, `source_keys`, etc), but most algorithms should only rely on the
`inputs` mapping.

Minimum shape to support:

```json
{
  "version": 1,
  "inputs": {
    "primary": "/work/input/some_input.ext"
  }
}
```

The default `entrypoint.py` template intentionally ignores extra fields and only uses `inputs`.
It also includes an *optional* NIfTI example that reorients to canonical (RAS+) orientation if
`nibabel` is installed; otherwise it falls back to copying the input.

### Output `content_type` (optional)

In the output manifest, each output can be either:

- a string path: `"some_key": "file.ext"`, or
- an object: `"some_key": {"path": "file.ext", "content_type": "..."}`

`content_type` is **optional**. If you omit it, the external runner will still upload the file,
but it won't set the S3 `ContentType` metadata. Providing it is useful when outputs are served
directly to browsers or other tools that rely on MIME type.

The algorithm container does **not** need to download/upload object storage artifacts directly.
The external runner handles object storage before and after execution.

## External runner environment variables

Copy `.env.example` to `.env` and set values:

- `RUNNER_TASK_NAME`: Celery task name consumed by this worker (normally keep `toothfairy4m_runner.process_job`)
- `RUNNER_QUEUE`: Celery queue this worker subscribes to
- `RUNNER_WORKER_ID`: worker identifier persisted on jobs
- `RUNNER_API_BASE_URL`: ToothFairy4M API base URL (for claim/complete/fail callbacks)
- `RUNNER_API_TOKEN`: bearer token that must exist in ToothFairy4M `RUNNER_API_TOKENS`
- `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`: broker/backend used by both web and worker
- `OBJECT_STORAGE_*`: S3-compatible endpoint and credentials used by runner for artifact I/O (Garage/MinIO)
- `ALGORITHM_IMAGE_MAP`: JSON map modality -> docker image
- `ALGORITHM_CONTAINER_CMD` (optional): command executed inside algorithm container (default: `python /app/entrypoint.py`)
- `RUNNER_WORKDIR_ROOT`: local staging path for downloaded inputs/output manifests

## Build

```bash
docker build -t toothfairy4m-{{ cookiecutter.algorithm_slug }}:latest .
```

Build (and tag) the algorithm image referenced in `ALGORITHM_IMAGE_MAP`.

## Run external worker

```bash
cp .env.example .env
docker run --rm \
  --env-file .env \
  -v /var/run/docker.sock:/var/run/docker.sock \
  toothfairy4m-{{ cookiecutter.algorithm_slug }}:latest
```

This starts a Celery worker with:

- queue `{{ cookiecutter.runner_queue }}`
- concurrency `1`
- prefetch multiplier `1`

## Run with Docker Compose

```bash
cp .env.compose.example .env
docker compose up --build -d
```

Useful commands:

```bash
docker compose logs -f runner
docker compose down
```

Compose runs one `runner` service that listens on `RUNNER_QUEUE` and uses the host Docker socket to start algorithm containers.
If your ToothFairy4M stack is on the same Docker network (instead of host ports), you can start from `.env.example` and adjust hostnames accordingly.

## Test algorithm logic locally (without Celery)

Prepare a folder like:

```text
work/
  input/
    manifest.json
    <your input files>
  output/
```

Run:

```bash
docker run --rm \
  --entrypoint python \
  -v "$PWD/work:/work" \
  -e TF_INPUT_MANIFEST=/work/input/manifest.json \
  -e TF_OUTPUT_MANIFEST=/work/output/manifest.json \
  toothfairy4m-{{ cookiecutter.algorithm_slug }}:latest \
  /app/entrypoint.py
```

Outputs will be in `work/output/`.
