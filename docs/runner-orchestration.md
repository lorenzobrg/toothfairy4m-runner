# ToothFairy4M runner orchestration (frontend/backend)

## Key distinction: scaffolding vs execution

- **Cookiecutter** is used at *development time* to generate a new package (Dockerfile + entrypoint + external runner code).
- **Docker** is used at *runtime* to execute an already-built algorithm image against an input manifest.

A browser frontend generally cannot (and should not) run Cookiecutter or control Docker directly.
Typically:

- Frontend: selects algorithm + uploads inputs + shows job status/results.
- External runner worker (runner/orchestrator): claims jobs via API, starts Docker algorithm container, uploads outputs, marks job complete/failed.

## Runtime contract

The runner/orchestrator provides two env vars inside the container:

- `TF_INPUT_MANIFEST` (path to JSON)
- `TF_OUTPUT_MANIFEST` (path to JSON)

The container must:

- Read `TF_INPUT_MANIFEST`
- Write output files into the directory containing `TF_OUTPUT_MANIFEST`
- Write an output-manifest JSON like:

```json
{
  "version": 1,
  "outputs": {
    "some_key": {"path": "file.ext", "content_type": "..."}
  }
}
```

The input manifest is typically shaped like:

```json
{
  "version": 1,
  "job": {"id": "job-123"},
  "inputs": {
    "primary": "/work/input/some_input.ext",
    "optional_secondary": "/work/input/other.ext"
  }
}
```

## Typical backend flow (docker run)

1. Create a per-job working directory on the host:

```text
/workspaces/jobs/<job_id>/
  input/
    manifest.json
    ...input files...
  output/
```

2. Run the algorithm image:

```bash
docker run --rm \
  -v "/workspaces/jobs/<job_id>:/work" \
  -e TF_INPUT_MANIFEST=/work/input/manifest.json \
  -e TF_OUTPUT_MANIFEST=/work/output/manifest.json \
  <algorithm-image>:<tag>
```

3. After the container exits:

- Read `/workspaces/jobs/<job_id>/output/manifest.json`
- Upload/store the listed output files
- Mark the job as completed/failed via ToothFairy4M Runner API with bearer token

## Where Cookiecutter fits

When a developer creates a new algorithm:

- Run Cookiecutter to scaffold the algorithm folder.
- Implement algorithm-specific logic in `entrypoint.py`.
- Build and push the Docker image to a registry.
- Configure generated external runner `ALGORITHM_IMAGE_MAP` to map modality to that image.
- Configure web `RUNNER_API_TOKENS` and runner `RUNNER_API_TOKEN`.

In this repo, the Cookiecutter template lives under `cookiecutter-toothfairy4m-runner/`.
