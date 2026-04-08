# ToothFairy4M Runner Cookiecutter

This repo is a Cookiecutter template for ToothFairy4M **algorithm containers**.

If you only care about implementing an algorithm, focus on the container contract and implement `entrypoint.py`.

## Implement the algorithm (`entrypoint.py`)

At runtime, the external runner/orchestrator starts your container and sets two env vars:

- `TF_INPUT_MANIFEST=/work/input/manifest.json`
- `TF_OUTPUT_MANIFEST=/work/output/manifest.json`

Your container must:

1) Read the JSON at `TF_INPUT_MANIFEST`
2) Write output file(s) under the directory containing `TF_OUTPUT_MANIFEST` (usually `/work/output/`)
3) Write an output manifest JSON to `TF_OUTPUT_MANIFEST`

### Input manifest (minimal shape)

The only field algorithms should *rely on* is `inputs`.
Extra fields may exist (e.g. `job`, `source_keys`) and can usually be ignored.

Example:

```json
{
  "version": 1,
  "inputs": {
    "primary": "/work/input/some_file.ext",
    "secondary": "/work/input/other_file.ext"
  },
  "job": {"id": 123}
}
```

Multiple input files are supported: `inputs` is a mapping of logical name → file path.
The convention is to include a `primary` key when there is a main input.

### Output manifest

Your container must write an output manifest like:

```json
{
  "version": 1,
  "outputs": {
    "some_output_key": {"path": "relative_filename.ext", "content_type": "..."}
  }
}
```

Notes:

- Output `path` must be either absolute or relative to `/work/output/`.
- `content_type` is optional. If omitted, the runner still uploads the file, but won’t set S3 `ContentType` metadata.
- The runner also accepts the short form: `"some_output_key": "relative_filename.ext"`.

## Quick local test (just the contract)

Create a working directory like:

```text
work/
  input/
    manifest.json
    <any input files>
  output/
```

Run the container:

```bash
docker run --rm \
  -v "$PWD/work:/work" \
  -e TF_INPUT_MANIFEST=/work/input/manifest.json \
  -e TF_OUTPUT_MANIFEST=/work/output/manifest.json \
  toothfairy4m-<algorithm_slug>:latest
```

After it completes, check `work/output/` for the produced file(s) and `manifest.json`.

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

If you need the external runner/orchestrator details, see `docs/runner-orchestration.md`.
