# youIntel

Utilities for the YouTube Intelligence Pipeline live in `youtube_transcript_pipeline/`.

## Prompt extraction testing

To reprocess saved transcript results with a prompt for comparison, use the pipeline utility documented in `youtube_transcript_pipeline/README.md`:

```bash
cd youtube_transcript_pipeline
PYTHONPATH=src python scripts/reprocess_transcripts_with_prompt.py \
  --input-dir outputs \
  --prompt-file topic_perspective_prompt.txt \
  --model gpt-5 \
  --output outputs/topic_prompt_v1_results.json
```

Set `OPENAI_API_KEY` before running. The utility also accepts `--prompt-text` for one-off prompt experiments and `--max-records` for quick smoke tests.
