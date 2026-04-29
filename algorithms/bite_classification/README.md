# Bite Classification

Bits2Bites-based bite classification runner for ToothFairy4M.

This package contains two components:

- `entrypoint.py`: algorithm container logic. Reads localized STL inputs from `/work/input`, runs inference, and writes a classification JSON under `/work/output`.
- `runner/`: external Celery worker. Claims jobs from ToothFairy4M API, downloads/uploads artifacts via object storage, runs the algorithm container, and reports completion/failure.

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

Implemented inference expects STL inputs (typically oriented `upper` and `lower`) and outputs
`*_bite_classification_results.json` with ToothFairy4M-compatible keys:

- `sagittal_left`
- `sagittal_right`
- `vertical`
- `transverse`
- `midline`

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

Copy `.env.compose.example` to `.env` and set values:

- `RUNNER_TASK_NAME`: Celery task name consumed by this worker (normally keep `toothfairy4m_runner.process_job`)
- `RUNNER_QUEUE`: Celery queue this worker subscribes to
- `RUNNER_WORKER_ID`: worker identifier persisted on jobs
- `RUNNER_API_BASE_URL`: ToothFairy4M API base URL (for claim/complete/fail callbacks)
- `RUNNER_API_TOKEN`: bearer token that must exist in ToothFairy4M `RUNNER_API_TOKENS`
- `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`: broker/backend used by both web and worker
- `OBJECT_STORAGE_*`: S3-compatible endpoint and credentials used by runner for artifact I/O (Garage/MinIO)
- `ALGORITHM_IMAGE_MAP`: JSON map modality -> docker image (use `bite_classification` key)
- `ALGORITHM_CONTAINER_CMD` (optional): command executed inside algorithm container (default: `python /app/entrypoint.py`)
- `ALGORITHM_CONTAINER_GPUS` (optional): value passed to `docker create --gpus` for spawned algorithm containers (default `all`; set empty to disable)
- `RUNNER_WORKDIR_ROOT`: local staging path for downloaded inputs/output manifests
- `TORCH_CUDA_ARCH_LIST`: build arch list for CUDA kernels (default `7.5` for RTX 2080 Ti)

## Build

Build from the `toothfairy4m-runner` root so Docker can include `Bits2Bites/` code and checkpoint:

```bash
cd /home/lborghi/toothfairy4m-runner
docker build \
  -f algorithms/bite_classification/Dockerfile \
  --build-arg TORCH_CUDA_ARCH_LIST="7.5" \
  -t toothfairy4m-bite_classification:latest \
  .
```

To target additional architectures, pass a wider list, for example:

```bash
--build-arg TORCH_CUDA_ARCH_LIST="7.5 8.0 8.6"
```

## Run external worker

```bash
cp .env.compose.example .env
docker run --rm \
  --env-file .env \
  -v /var/run/docker.sock:/var/run/docker.sock \
  toothfairy4m-bite_classification:latest
```

This starts a Celery worker with:

- queue `runner_bite_dev`
- concurrency `1`
- prefetch multiplier `1`

## Run with Docker Compose

```bash
cd /home/lborghi/toothfairy4m-runner/algorithms/bite_classification
cp .env.compose.example .env
docker compose up --build -d
```

Useful commands:

```bash
docker compose logs -f runner
docker compose down
```

Compose runs one `runner` service that listens on `RUNNER_QUEUE` and uses the host Docker socket to start algorithm containers.

For two-stage IOS pipelines, configure ToothFairy4M with:

- `ios -> runner_ios_dev`
- `bite_classification -> runner_bite_dev`

## Test algorithm logic locally (without Celery)

Prepare a folder like:

```text
work/
  input/
    manifest.json
    upper.stl
    lower.stl
  output/
```

Run:

```bash
docker run --rm \
  --entrypoint python \
  -v "$PWD/work:/work" \
  -e TF_INPUT_MANIFEST=/work/input/manifest.json \
  -e TF_OUTPUT_MANIFEST=/work/output/manifest.json \
  toothfairy4m-bite_classification:latest \
  /app/entrypoint.py
```

Outputs will be in `work/output/` and include:

- classification JSON (`*_bite_classification_results.json`)
- output manifest (`manifest.json`)
