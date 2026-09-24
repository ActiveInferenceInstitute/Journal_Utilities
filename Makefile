.PHONY: help install install-dev clean test lint format db-start transcribe fetch-coda import-sessions fetch-metadata copy-to-journal extract-entities enumerate-channel download-transcripts download-audio download-video download-all journal-enrich journal-enrich-apply journal-index journal-repair journal-check

JOURNAL_DIR ?= ../ActiveInferenceJournal
MANIFEST ?= data/output/channel_videos.json

# Load .env file if it exists
ifneq (,$(wildcard .env))
    include .env
    export
endif

help:
	@echo "Available commands:"
	@echo ""
	@echo "Installation & Setup:"
	@echo "  make install      - Install project dependencies"
	@echo "  make install-dev  - Install project with dev dependencies"
	@echo "  make clean        - Clean up cache and temporary files"
	@echo ""
	@echo "Development:"
	@echo "  make test         - Run tests"
	@echo "  make lint         - Run linter (ruff)"
	@echo "  make format       - Format code with black"
	@echo "  make journal-check - Validate the sibling journal (read-only)"
	@echo ""
	@echo "Database:"
	@echo "  make db-start     - Start SurrealDB"
	@echo ""
	@echo "Transcription Pipeline:"
	@echo "  make fetch-coda   - Fetch latest data from Coda API"
	@echo "  make transcribe   - Run local transcription (mlx-whisper, Apple Silicon)"
	@echo "  (make import-sessions, fetch-metadata, copy-to-journal are retired;"
	@echo "   they print guidance and exit 2)"
	@echo ""
	@echo "Entity Extraction Pipeline:"
	@echo "  make extract-entities - Extract entities from transcripts (Cohere AI)"
	@echo ""
	@echo "YouTube Channel Download:"
	@echo "  make enumerate-channel    - Enumerate all videos on the channel"
	@echo "  make download-transcripts - Download transcripts for all channel videos"
	@echo "  make download-audio       - Download audio (MP3) for all channel videos"
	@echo "  make download-video       - Download video for all channel videos"
	@echo "  make download-all         - Download transcripts, audio, and video"
	@echo ""
	@echo "Journal v2 maintenance (JOURNAL_DIR=$(JOURNAL_DIR)):"
	@echo "  make journal-enrich       - Preview metadata enrichment (dry run)"
	@echo "  make journal-enrich-apply - Apply metadata enrichment explicitly"
	@echo "  make journal-repair       - Rebuild complete split transcripts"
	@echo "  make journal-index        - Regenerate INDEX.json and INDEX.md"
	@echo "  make journal-check        - Run the complete read-only integrity gate"

install:
	uv sync

install-dev:
	uv sync --all-extras

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache
	rm -rf .ruff_cache
	rm -rf build dist *.egg-info

test:
	uv run pytest tests/

lint:
	uv run ruff check src/ tests/ scripts/

format:
	uv run ruff format src/ tests/
	uv run ruff check --fix src/ tests/

db-start:
	surreal start --log trace --user root --pass root --bind 0.0.0.0:8080 rocksdb://./data/database

fetch-coda:
	@echo "Fetching latest data from Coda API..."
	@if [ -z "$(CODA_API_TOKEN)" ]; then \
		echo "Error: CODA_API_TOKEN not found in .env file"; \
		exit 1; \
	fi
	@mkdir -p data/input
	@curl -X GET "https://coda.io/apis/v1/docs/TwB_SP81yq/tables/grid-cjvFiXp3a3/rows?useColumnNames=true" \
		-H "Authorization: Bearer $(CODA_API_TOKEN)" \
		-o data/input/livestream_fulldata_table.json
	@echo "Data saved to data/input/livestream_fulldata_table.json"

import-sessions:
	@echo "The legacy database import target is retired."
	@echo "Use: uv run python scripts/enrich_metadata.py --journal $(JOURNAL_DIR)"
	@exit 2

fetch-metadata:
	@echo "The legacy database metadata target is retired."
	@echo "Use: make enumerate-channel followed by make journal-enrich"
	@exit 2

transcribe:
	@echo "Starting local transcription pipeline..."
	uv run python scripts/transcribe_missing.py

copy-to-journal:
	@echo "The legacy database copy target is retired."
	@echo "Use: make journal-repair journal-index journal-check"
	@exit 2

extract-entities:
	@echo "Extracting entities from transcripts using Cohere AI..."
	@if [ -z "$(COHERE_API_KEY)" ]; then \
		echo "Error: COHERE_API_KEY not found in .env file"; \
		exit 1; \
	fi
	uv run python -m journal_utilities.rag.main

enumerate-channel:
	@echo "Enumerating videos on the Active Inference channel..."
	uv run python scripts/download_channel.py --enumerate-only

download-transcripts:
	@echo "Downloading transcripts for all channel videos..."
	uv run python scripts/download_channel.py --transcripts --resume

download-audio:
	@echo "Downloading audio (MP3) for all channel videos..."
	uv run python scripts/download_channel.py --audio --resume

download-video:
	@echo "Downloading video for all channel videos..."
	uv run python scripts/download_channel.py --video --resume

download-all:
	@echo "Downloading transcripts, audio, and video for all channel videos..."
	uv run python scripts/download_channel.py --transcripts --audio --video --resume

journal-enrich:
	uv run python scripts/enrich_metadata.py --journal $(JOURNAL_DIR) --manifest $(MANIFEST)

journal-enrich-apply:
	uv run python scripts/enrich_metadata.py --journal $(JOURNAL_DIR) --manifest $(MANIFEST) --apply

journal-repair:
	uv run python scripts/repair_split_transcripts.py --journal $(JOURNAL_DIR) --utilities .

journal-index:
	uv run python scripts/generate_journal_indexes.py --journal $(JOURNAL_DIR)

journal-check:
	uv run python run.py journal-check --journal $(JOURNAL_DIR) --utilities . --manifest $(MANIFEST)

yt-dryrun:
	uv run python scripts/sync_youtube_metadata.py --dry-run $(if $(VIDEO),--video-id $(VIDEO),)
