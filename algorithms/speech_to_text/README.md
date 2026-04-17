# Speech To Text Runner

This runner executes Whisper speech-to-text for ToothFairy4M voice captions.

## What it does

- Loads Whisper model `large` (`self.audio_model = whisper.load_model("large")` behavior).
- Transcribes in Italian (`language="it"`).
- Writes a text output with suffix `_transcription.txt`.
- Preserves ToothFairy4M storage compatibility by converting paths from `raw` to `processed`.
- Uses canonical modality slug `audio`, with legacy alias `voice` still mapped.

## Contract

The algorithm container reads:

- `TF_INPUT_MANIFEST=/work/input/manifest.json`
- `TF_OUTPUT_MANIFEST=/work/output/manifest.json`

And writes an output manifest:

```json
{
  "version": 1,
  "outputs": {
    "transcription": {
      "path": "..._transcription.txt",
      "content_type": "text/plain"
    }
  }
}
```

## Modality Compatibility

ToothFairy4M currently creates speech-to-text jobs as `modality_slug="audio"`.

This runner keeps compatibility by:

- listening on `RUNNER_QUEUE=runner_audio_dev` by default,
- mapping both `audio` and `voice` in `ALGORITHM_IMAGE_MAP`.

For ToothFairy4M routing, make sure `RUNNER_QUEUE_BY_MODALITY` includes audio, for example:

```json
{"ios":"runner_ios_dev","bite_classification":"runner_bite_dev","cbct":"runner_cbct_dev","audio":"runner_audio_dev","voice":"runner_audio_dev"}
```

## Build

```bash
docker build -t toothfairy4m-speech_to_text:latest .
```

## Run With Compose

```bash
cp .env.compose.example .env
docker compose up --build -d
```

Useful commands:

```bash
docker compose logs -f runner
docker compose down
```

## Local Algorithm Test

```bash
docker run --rm \
  --entrypoint python \
  -v "$PWD/work:/work" \
  -e TF_INPUT_MANIFEST=/work/input/manifest.json \
  -e TF_OUTPUT_MANIFEST=/work/output/manifest.json \
  toothfairy4m-speech_to_text:latest \
  /app/entrypoint.py
```
