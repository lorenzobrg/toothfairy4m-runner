# {{ cookiecutter.algorithm_name }}

{{ cookiecutter.algorithm_description }}

## Runner contract

The runner provides:

- `TF_INPUT_MANIFEST=/work/input/manifest.json`
- `TF_OUTPUT_MANIFEST=/work/output/manifest.json`

Your container must:

- Read the input manifest JSON
- Write all output files under `/work/output/`
- Write the output manifest JSON to `TF_OUTPUT_MANIFEST`

## Build

```bash
docker build -t toothfairy4m-{{ cookiecutter.algorithm_slug }}:latest .
```

## Run (local)

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
  -v "$PWD/work:/work" \
  -e TF_INPUT_MANIFEST=/work/input/manifest.json \
  -e TF_OUTPUT_MANIFEST=/work/output/manifest.json \
  toothfairy4m-{{ cookiecutter.algorithm_slug }}:latest
```

Outputs will be in `work/output/`.
