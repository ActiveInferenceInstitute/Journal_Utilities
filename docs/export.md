# Export Module

The Export module (`src/journal_utilities/export/`) handles the conversion of transcripts into various distribution formats.

## Architecture

The module uses a functional strategy pattern where each `ExportFormat` is mapped to a specific writer function.

### Core Functions (`exporter.py`)

The module uses a functional strategy pattern — each `ExportFormat` is mapped to a writer function. There is no class; all logic is in top-level functions.

- **Input**: Directory of `.txt` transcript files.
- **Output**: Subdirectories for each format (`pdf/`, `json/`, etc.).
- **Concurrency**: Sequential processing (CPU-bound/IO-bound).

## Supported Formats

| Format | Extension | Library | Implementation Details |
| :--- | :--- | :--- | :--- |
| **Plaintext** | `.txt` | Built-in | Metadata header (title, category, speakers, duration, URL), UTF-8. |
| **Markdown** | `.md` | Built-in | YAML frontmatter (title, category, series, episode, speakers, duration, URL, views). |
| **JSON** | `.json` | Built-in | Structured data including metadata, word count, and transcript. |
| **HTML** | `.html` | Built-in | Standalone file with embedded CSS, metadata subtitle, and YouTube link. |
| **PDF** | `.pdf` | `fpdf2` | Clean typography with title + metadata subtitle, sanitized Unicode. |

## Usage

### CLI

The export module is typically invoked via the main `run.py` runner:

```bash
# Export all configured formats
python run.py export
```

### Library

```python
from journal_utilities.export.exporter import export_transcripts, ExportFormat
from pathlib import Path

export_transcripts(
    transcript_dir=Path("data/output/transcripts"),
    output_dir=Path("data/export"),
    formats=[ExportFormat.PDF, ExportFormat.MARKDOWN],
    data_dir=Path("data/output"),  # enables metadata enrichment
)
```

## Metadata Enrichment

When `data_dir` is provided, the exporter loads `channel_videos.json` and enriches every export with:

- **Title**: Full video title (replaces YouTube ID)
- **Category/Series/Episode**: From the categorizer heuristics
- **Speakers**: Parsed from titles (text after `~`)
- **Duration**: Formatted as `H:MM:SS`
- **URL**: Direct YouTube link
- **Views**: View count

## Configuration

In `config.ini`:

```ini
[export]
# Enable/disable specific formats
plaintext = true
markdown = true
pdf = true
json = true
html = true

# Output directory relative to project root
output_dir = data/export
```

## Required export completion

`run.py export` returns nonzero when no outcomes are produced or any requested
export fails, including mixed-success batches. Successfully written or
already-existing nonempty outputs remain available. `full` and the default
pipeline propagate required export failure; the default pipeline does not
continue to tests or serving after that failure, independently of `test_strict`.
