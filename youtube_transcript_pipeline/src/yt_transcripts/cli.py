from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from yt_transcripts.config import configure_logging
from yt_transcripts.db.session import init_db
from yt_transcripts.services.batch import BatchProcessor
from yt_transcripts.services.channel_service import ChannelService
from yt_transcripts.services.latest_videos_transcript_service import LatestVideosTranscriptService
from yt_transcripts.services.pipeline import TranscriptPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="YouTube transcript pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    single = subparsers.add_parser("single", help="Fetch transcript for one video")
    single.add_argument("video", help="YouTube URL or video ID")
    single.add_argument("--languages", nargs="*", default=["en"])
    single.add_argument("--disable-ytdlp-fallback", action="store_true")
    single.add_argument("--enable-whisper-fallback", action="store_true")
    single.add_argument("--whisper-model", default=os.getenv("WHISPER_MODEL", "base"))
    single.add_argument("--whisper-language", default=os.getenv("WHISPER_LANGUAGE"))
    single.add_argument("--output-json", default="")

    batch = subparsers.add_parser("batch", help="Process latest videos for channels")
    batch.add_argument("--channel-id", action="append", required=True, dest="channel_ids")
    batch.add_argument("--max-videos", type=int, default=5)
    batch.add_argument("--languages", nargs="*", default=["en"])
    batch.add_argument("--disable-ytdlp-fallback", action="store_true")
    batch.add_argument("--enable-whisper-fallback", action="store_true")
    batch.add_argument("--whisper-model", default=os.getenv("WHISPER_MODEL", "base"))
    batch.add_argument("--whisper-language", default=os.getenv("WHISPER_LANGUAGE"))
    batch.add_argument("--output-dir", default="outputs")

    batch_config = subparsers.add_parser(
        "batch-from-config",
        help="Process latest videos for channels from a YAML config file",
    )
    batch_config.add_argument("--channels-config", default="config/channels.yaml")
    batch_config.add_argument("--include-disabled", action="store_true")
    batch_config.add_argument("--max-videos", type=int, default=5)
    batch_config.add_argument("--languages", nargs="*", default=["en"])
    batch_config.add_argument("--disable-ytdlp-fallback", action="store_true")
    batch_config.add_argument("--enable-whisper-fallback", action="store_true")
    batch_config.add_argument("--whisper-model", default=os.getenv("WHISPER_MODEL", "base"))
    batch_config.add_argument("--whisper-language", default=os.getenv("WHISPER_LANGUAGE"))
    batch_config.add_argument("--output-dir", default="outputs")

    analyze = subparsers.add_parser(
        "analyze-topics",
        help="Analyze downloaded transcripts and aggregate topics by channel perspective",
    )
    analyze.add_argument("--input-dir", default="outputs")
    analyze.add_argument("--model", default=os.getenv("OPENAI_ANALYSIS_MODEL", "gpt-5"))
    analyze.add_argument("--prompt-file", default="topic_perspective_prompt.txt")
    analyze.add_argument("--output-file", default="outputs/topic_perspectives_aggregate.json")
    analyze.add_argument("--prompt-version", default="v1")
    analyze.add_argument("--force", action="store_true")

    subparsers.add_parser("init-db", help="Initialize database schema")

    return parser


def main() -> None:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init-db":
        init_db()
        print(json.dumps({"status": "ok", "message": "database initialized"}, indent=2))
        return

    if args.command == "single":
        pipeline = TranscriptPipeline()
        result = pipeline.get_transcript(
            video=args.video,
            languages=args.languages,
            enable_ytdlp_fallback=not args.disable_ytdlp_fallback,
            enable_whisper_fallback=args.enable_whisper_fallback,
            whisper_model=args.whisper_model,
            whisper_language=args.whisper_language,
        )
        print(json.dumps(result.to_dict(), indent=2))
        if args.output_json:
            Path(args.output_json).write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        return

    if args.command == "batch":
        processor = BatchProcessor()
        results = processor.process_latest_videos(
            channel_ids=args.channel_ids,
            max_videos_per_channel=args.max_videos,
            languages=args.languages,
            enable_ytdlp_fallback=not args.disable_ytdlp_fallback,
            enable_whisper_fallback=args.enable_whisper_fallback,
            whisper_model=args.whisper_model,
            whisper_language=args.whisper_language,
            output_dir=args.output_dir,
        )
        print(json.dumps({"processed": len(results), "output_dir": args.output_dir}, indent=2))

    if args.command == "batch-from-config":
        channel_service = ChannelService(config_path=args.channels_config)
        processor = LatestVideosTranscriptService(channel_service=channel_service)
        results = processor.process_configured_channels(
            max_videos_per_channel=args.max_videos,
            languages=args.languages,
            enable_ytdlp_fallback=not args.disable_ytdlp_fallback,
            enable_whisper_fallback=args.enable_whisper_fallback,
            whisper_model=args.whisper_model,
            whisper_language=args.whisper_language,
            output_dir=args.output_dir,
            enabled_only=not args.include_disabled,
        )
        print(
            json.dumps(
                {
                    "processed": len(results),
                    "output_dir": args.output_dir,
                    "channels_config": args.channels_config,
                },
                indent=2,
            )
        )


    if args.command == "analyze-topics":
        from yt_transcripts.services.transcript_intelligence_pipeline import TranscriptIntelligencePipeline

        pipeline = TranscriptIntelligencePipeline()
        result = pipeline.run(
            input_dir=args.input_dir,
            model=args.model,
            prompt_file=args.prompt_file,
            output_file=args.output_file,
            prompt_version=args.prompt_version,
            force=args.force,
        )
        print(
            json.dumps(
                {
                    "analyzed_videos": result["analyzed_videos"],
                    "aggregation_collections": len(result["aggregations"]),
                    "output_file": args.output_file,
                    "model": args.model,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
