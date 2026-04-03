# ToothFairy4M Runner Cookiecutter

This repository is a **Cookiecutter template** for implementing ToothFairy4M algorithm packages that include both:

- an algorithm container entrypoint (`entrypoint.py`)
- an external Celery runner (`runner/`) that executes jobs outside the ToothFairy4M web app

A ToothFairy4M algorithm container:

- Receives `TF_INPUT_MANIFEST` and `TF_OUTPUT_MANIFEST` as environment variables.
- Reads the input manifest JSON (which includes `job` and `inputs`).
- Writes all generated files into the directory that contains the output manifest.
- Writes an output manifest JSON describing its outputs:

```json
{
  "version": 1,
  "outputs": {
    "some_output_key": {"path": "relative_filename.ext", "content_type": "..."}
  }
}
```

The input manifest is expected to be shaped roughly like:

```json
{
  "version": 1,
  "job": {"id": "..."},
  "inputs": {
    "some_logical_name": "/work/input/some_file.ext"
  }
}
```

## Generate a new algorithm

This repo contains sample runners in `tmp/` for reference.
To avoid copying those into your generated project, run Cookiecutter against the template directory:

```bash
cookiecutter cookiecutter-toothfairy4m-runner
```

Cookiecutter will create a new folder named after `algorithm_slug`.

## Build the generated image

```bash
docker build -t toothfairy4m-<algorithm_slug>:latest <algorithm_slug>
```

Then set `ALGORITHM_IMAGE_MAP` in the generated runner `.env` to point each modality to the image tag you built.

## Run external runner (production-like)

After generating a project:

```bash
cp .env.example .env
docker run --rm \
  --env-file .env \
  -v /var/run/docker.sock:/var/run/docker.sock \
  toothfairy4m-<algorithm_slug>:latest \
  python -m celery -A runner.celery_app worker -l info -Q <runner_queue> --concurrency=1 --prefetch-multiplier=1 -O fair
```

This worker will:

- consume Celery tasks (`toothfairy4m_runner.process_job`)
- claim/complete/fail jobs through web API token auth
- download RAW artifacts and upload processed artifacts in S3-compatible object storage (Garage/MinIO)

## Run only the algorithm contract locally

Create a working directory like:

```text
work/
  input/
    manifest.json
    <any input files>
  output/
```

Then run:

```bash
docker run --rm \
  -v "$PWD/work:/work" \
  -e TF_INPUT_MANIFEST=/work/input/manifest.json \
  -e TF_OUTPUT_MANIFEST=/work/output/manifest.json \
  toothfairy4m-<algorithm_slug>:latest
```

After it completes, check `work/output/` for the produced files and `manifest.json`.

## Frontend note

Cookiecutter is typically used at **development time** to scaffold a new algorithm.
Running the algorithm container is done by the generated external runner, not by the browser frontend.
