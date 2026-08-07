# YouTube Transcript Pipeline

Small package layout for pulling transcripts from YouTube with fallbacks and batch processing for the latest 5 videos per channel.

## Structure

```text
src/yt_transcripts/
  clients/
  models/
  services/
  cli.py
config/
  channels.yaml
prompts/
  topic_perspective_prompt.txt
```

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment

Copy `.env.example` to `.env` and add your YouTube Data API key.

Transcript retrieval duration guardrails are configurable through `.env`:

```bash
TRANSCRIPT_MIN_VIDEO_SECONDS=180
TRANSCRIPT_MAX_VIDEO_SECONDS=1200
```

Videos shorter than the minimum or longer than the maximum are skipped and written as structured `no_transcript` results.

## Single video

```bash
PYTHONPATH=src python -m yt_transcripts.cli single "https://www.youtube.com/watch?v=_XOV3I0EVBA"
```

Enable Whisper fallback explicitly:

```bash
PYTHONPATH=src python -m yt_transcripts.cli single "https://www.youtube.com/watch?v=_XOV3I0EVBA" --enable-whisper-fallback --whisper-model tiny
```


## Build `channels.yaml` from channel names

You can generate `config/channels.yaml` directly from a list of channel names:

```bash
PYTHONPATH=src python scripts/build_channels_yaml.py \
  --channel-name "Google for Developers" \
  --channel-name "Marques Brownlee" \
  --output config/channels.yaml
```

Or pass a text file with one channel name per line:

```bash
PYTHONPATH=src python scripts/build_channels_yaml.py \
  --input-file channel_names.txt \
  --output config/channels.yaml
```

The command prints unresolved channel names so you can review ambiguous or missing matches.

## Batch latest 5 videos (explicit channels)

```bash
PYTHONPATH=src python -m yt_transcripts.cli batch \
  --channel-id UC_x5XG1OV2P6uZZ5FSM9Ttw \
  --channel-id UCBJycsmduvYEL83R_U4JriQ \
  --max-videos 5 \
  --output-dir outputs
```

## Batch latest 5 videos (YAML channel config)

Create/update `config/channels.yaml`:

```yaml
version: 1
channels:
  - name: Google for Developers
    channel_id: UC_x5XG1OV2P6uZZ5FSM9Ttw
    enabled: true
```

Run configured channels:

```bash
PYTHONPATH=src python -m yt_transcripts.cli batch-from-config \
  --channels-config config/channels.yaml \
  --max-videos 5 \
  --output-dir outputs
```

This command uses `ChannelService` to load channels and `LatestVideosTranscriptService` to orchestrate retrieval for future extension points (processing, summarization, and persistence).

This writes one JSON file per video plus `batch_summary.json`.

## Analyze downloaded transcripts with GPT-5

Set `OPENAI_API_KEY` in your environment, then run:

```bash
PYTHONPATH=src python -m yt_transcripts.cli analyze-topics \
  --input-dir /outputs \
  --model gpt-5 \
  --prompt-file topic_perspective_prompt.txt \
  --output-file /outputs/topic_perspectives_aggregate.json
```

This command:
- Loads prompts from `prompts/`
- Analyzes each transcript JSON inside `/outputs`
- Detects topics and per-topic channel perspectives
- Aggregates topics across channels and attributes which channels supplied each perspective

## Database setup and usage

Set `DATABASE_URL` in `.env` (Postgres example: `postgresql+psycopg://user:pass@localhost:5432/ytintel`).

Initialize schema:

```bash
python -m yt_transcripts.cli init-db
```


For existing databases created before these fields were added, run:

```bash
PYTHONPATH=src python scripts/migrate_add_channel_video_metrics.py
```

Run transcript fetch and persist:

```bash
python -m yt_transcripts.cli batch-from-config --channels-config config/channels.yaml --max-videos 5 --output-dir outputs
```

Run analysis and persist:

```bash
python -m yt_transcripts.cli analyze-topics --input-dir outputs --prompt-file topic_perspective_prompt.txt --prompt-version v1
```

Example SQL query:

```sql
SELECT v.youtube_video_id, va.summary, va.main_topics_json
FROM video_analyses va
JOIN videos v ON v.id = va.video_id
WHERE v.youtube_video_id = 'VIDEO_ID_HERE';
```

### Channel and video metric tracking

The pipeline stores channel subscriber counts (`channels.subscriber_count`) and per-video engagement metrics (`videos.view_count`, `videos.like_count`) on each run.

## Analyze database query results with OpenAI

Edit the `QUERY` constant in `scripts/analyze_query_results_with_openai.py` to define the read-only `SELECT`/`WITH` query to run against `DATABASE_URL`. Customize the prompt in `prompts/query_results_analysis_prompt.txt`, then run:

```bash
PYTHONPATH=src python scripts/analyze_query_results_with_openai.py \
  --model gpt-5 \
  --prompt-file prompts/query_results_analysis_prompt.txt \
  --output outputs/query_results_analysis.json
```

The utility writes a JSON artifact containing the model name, prompt file, executed query, returned row count, and OpenAI analysis text. The script rejects mutation queries so it can be used safely as a read-only reporting helper.
