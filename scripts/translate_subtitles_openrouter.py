#!/usr/bin/env python3
"""Translate ActiveInferenceJournal caption SRTs into target languages via OpenRouter.

Fast, resumable, idempotent subtitle translator. Key design points: (1) many subtitle cues are translated per HTTP
request (batch), not one HTTP round-trip per cue; (2) requests run concurrently
against a hosted API instead of a serialized local GPU.

Writes ``translations/<translation-title>.<lang>.srt`` beside each item,
preserving SRT index, timing and CRLF, matching docs/JOURNAL_SCHEMA.md.
Caption files whose exact bytes are duplicated across multiple item folders
(copied placeholders) are skipped and reported — translating them would
attribute one video's content to unrelated items.

Usage:
  python3 scripts/translate_subtitles_openrouter.py                      # all series
  python3 scripts/translate_subtitles_openrouter.py --series GuestStream
  python3 scripts/translate_subtitles_openrouter.py --lang es --lang fr
  python3 scripts/translate_subtitles_openrouter.py --force              # re-translate existing

Environment:
  OPENROUTER_API_KEY  (required — export it, or set it in the repo's gitignored .env)
  OPENROUTER_BASE_URL (default https://openrouter.ai/api/v1)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

TARGET_LANGS = ["es", "fr", "de", "pt", "it", "nl", "ru", "ja", "ko", "zh-Hans", "zh-Hant"]
LANGUAGE_NAMES = {
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
    "it": "Italian",
    "nl": "Dutch",
    "ru": "Russian",
    "ja": "Japanese",
    "ko": "Korean",
    "zh-Hans": "Simplified Chinese",
    "zh-Hant": "Traditional Chinese",
}
KEEP_VERBATIM = [
    "Active Inference Institute",
    "Active Inference",
    "pymdp",
    "Youtube",
    "YouTube",
    "Discord",
    "GitHub",
    "ActiveInferenceInstitute",
    "ActiveInference",
]
DEFAULT_MODEL = "openai/gpt-4o-mini"
DEFAULT_BATCH = 60
DEFAULT_WORKERS = 8
MAX_RETRIES = 5


def _post_chat(base_url: str, api_key: str, body: bytes, timeout: int = 180) -> dict:
    url = f"{base_url.rstrip('/')}/chat/completions"
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "journal-subtitle-translation",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def translate_batch(
    texts: list[str], lang: str, model: str, api_key: str, base_url: str, max_tokens: int = 16000
) -> list[str]:
    """Translate a batch of cue texts; returns exactly len(texts) entries or raises."""
    langname = LANGUAGE_NAMES[lang]
    keep = ", ".join(f'"{k}"' for k in KEEP_VERBATIM)
    system = (
        "You are a translation engine. The user message is a JSON array of short English "
        f"subtitle lines. Translate EVERY line into {langname}. "
        "Return a JSON array of translated strings, exactly one per input line, in the same order. "
        "No keys, no numbering, no commentary, no markdown. Do not drop or merge lines. "
        f"Keep these terms exactly as written: {keep}. "
        "Keep placeholder tokens like {n}, {title}, {count} unchanged. "
        "Match the length and register of the source - short subtitles stay short."
    )
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(texts, ensure_ascii=False)},
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
        }
    ).encode("utf-8")

    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            data = _post_chat(base_url, api_key, body)
            raw = (data["choices"][0]["message"].get("content") or "").strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)
            parsed = json.loads(raw)
            if not isinstance(parsed, list) or len(parsed) != len(texts):
                raise ValueError(f"got {len(parsed)} translations for {len(texts)} inputs")
            out = []
            for i, t in enumerate(parsed):
                if isinstance(t, list):
                    t = t[0] if t else ""
                out.append(str(t or texts[i]).strip())
            # Lenient echo guard: reject only if nearly all non-trivial cues came
            # back byte-identical (a degraded full-English response). Short
            # interjections that legitimately stay unchanged are excluded.
            trivial = sum(1 for s in texts if len(s.strip()) <= 3)
            echoes = sum(
                1 for tr, src in zip(out, texts, strict=True) if tr == src and len(src.strip()) > 3
            )
            if len(texts) >= 8 and echoes >= 0.9 * (len(texts) - trivial):
                raise ValueError("batch looks like an English echo")
            return out
        except Exception as e:
            last_err = e
            sleep_sec = 2**attempt
            time.sleep(sleep_sec)  # backoff: 1, 2, 4, 8, 16
    raise RuntimeError(f"translate_batch failed after {MAX_RETRIES} tries: {last_err}")


def load_api_key() -> str:
    """Resolve OPENROUTER_API_KEY from the environment or the repo's .env file."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if key and key.strip():
        return key.strip()
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("OPENROUTER_API_KEY="):
                value = line.split("=", 1)[1].strip()
                if value:
                    return value
    raise SystemExit("OPENROUTER_API_KEY not found (export it or set it in the repo .env file)")


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--journal",
        type=Path,
        default=Path(__file__).resolve().parent.parent.parent / "ActiveInferenceJournal",
    )
    ap.add_argument(
        "--series",
        default="",
        help="limit to one series dir under data/video/activeinferenceinstitute/",
    )
    ap.add_argument(
        "--lang", action="append", default=[], help="target lang code (repeatable); default all"
    )
    ap.add_argument("--limit", type=int, default=0, help="max caption files to translate (0=all)")
    ap.add_argument(
        "--force", action="store_true", help="re-translate languages that already exist"
    )
    ap.add_argument("--skip-to", type=int, default=0, help="resume at Nth caption file (1-based)")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="OpenRouter model")
    ap.add_argument("--batch", type=int, default=DEFAULT_BATCH, help="cues per request")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="concurrent requests")
    return ap.parse_args(argv)


def _translate_chunk(
    gidxs: list[int],
    parsed: list[tuple[list[str], list[str]]],
    lang: str,
    model: str,
    api_key: str,
    base_url: str,
) -> tuple[dict[int, str | None], int]:
    """Translate the cue-lines at block indexes gidxs.

    On failure split in half and recurse down to single cues.
    Returns (block_index -> text, fallback_count).
    """
    texts = ["\n".join(parsed[i][1]) for i in gidxs]
    try:
        translated = translate_batch(texts, lang, model, api_key, base_url)
        return {i: translated[k] for k, i in enumerate(gidxs)}, 0
    except Exception:
        if len(gidxs) == 1:
            return {gidxs[0]: None}, 1  # fall back to source for this single cue
        mid = len(gidxs) // 2
        left, fl = _translate_chunk(gidxs[:mid], parsed, lang, model, api_key, base_url)
        right, fr = _translate_chunk(gidxs[mid:], parsed, lang, model, api_key, base_url)
        left.update(right)
        return left, fl + fr


def translate_srt(
    srt_text: str, lang: str, model: str, api_key: str, base_url: str, batch: int, workers: int
) -> tuple[str, int, int]:
    """Translate an SRT's cue bodies, preserving index/timing/CRLF.

    Returns (new_srt_text, fallback_count, cue_count).
    """
    norm_text = srt_text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", norm_text.strip())
    parsed: list[tuple[list[str], list[str]]] = []
    for block in blocks:
        lines = [ln for ln in block.split("\n")]
        body = [ln for ln in lines if ln.strip() and "-->" not in ln and not ln.strip().isdigit()]
        parsed.append((lines, body))

    cue_indexes = [i for i, (_, b) in enumerate(parsed) if b]
    batches = [cue_indexes[s : s + batch] for s in range(0, len(cue_indexes), batch)]

    new_text: dict[int, str | None] = {}
    fallbacks = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(_translate_chunk, g, parsed, lang, model, api_key, base_url): g
            for g in batches
        }
        for fut in as_completed(futures):
            mapping, fb = fut.result()
            new_text.update(mapping)
            fallbacks += fb

    rebuilt = []
    for i, (lines, body) in enumerate(parsed):
        if body:
            txt = new_text.get(i)
            if txt is None:
                txt = "\n".join(body)  # fallback: keep source text
            kept = [ln for ln in lines if not ln.strip() or "-->" in ln or ln.strip().isdigit()]
            rebuilt.append("\n".join(kept + ([txt] if txt else [])))
        else:
            rebuilt.append("\n".join(lines))
    result = "\n\n".join(rebuilt) + "\n"
    return result.replace("\n", "\r\n"), fallbacks, len(cue_indexes)


def translation_filename(source_srt: Path, lang: str) -> str:
    name = source_srt.name
    if name.endswith(".en.srt"):
        base = name[: -len(".en.srt")]
    elif name.endswith(".srt"):
        base = name[: -len(".srt")]
        if base.rsplit(".", 1)[-1] in {"m4a"}:
            base = base[: -len(".m4a")]
    else:
        base = name
    return f"{base}.{lang}.srt"


def existing_translation(item_dir: Path, dest_name: str) -> Path | None:
    """An already-produced translation file, in either translations/ spelling.

    Checks lowercase ``translations/`` first, then legacy ``Translations/``, so
    the driver never re-pays for output that exists under either spelling.
    """
    for dir_name in ("translations", "Translations"):
        cand = item_dir / dir_name / dest_name
        if cand.exists():
            return cand
    return None


def iter_caption_files(journal: Path, series: str) -> list[Path]:
    base = journal / "data" / "video" / "activeinferenceinstitute"
    if series:
        base = base / series
    return sorted(base.rglob("captions/*.srt"))


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _caption_signature(journal: Path) -> str:
    """Cheap manifest of caption files → mtime, to invalidate the placeholder cache."""
    entries = [
        (str(p.relative_to(journal)), int(p.stat().st_mtime))
        for p in journal.rglob("captions/*.srt")
    ]
    entries.sort()
    h = hashlib.sha1()
    h.update(repr(entries).encode("utf-8"))
    return h.hexdigest()


def build_placeholder_hashes(journal: Path, use_cache: bool = True) -> dict[str, int]:
    """Map content-md5 -> count of distinct item dirs holding that exact caption.

    A caption file whose exact bytes appear under several different item folders
    is a copied placeholder (the journal has a known case: a Textbook Group
    transcript duplicated across ~63 items in ~10 series). Translating it would
    attribute that content to unrelated videos, so the driver skips those files
    and reports them instead.

    The scan walks the whole journal and is md5-dominated, so results are cached
    to a sidecar keyed on the journal's caption-directory mtime signature.
    """
    import tempfile

    cache_dir = Path(tempfile.gettempdir()) / "transl_subtitles_cache"
    cache_path = cache_dir / (
        hashlib.sha1(str(journal.resolve()).encode("utf-8")).hexdigest() + ".json"
    )
    if use_cache and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            counts = cached.get("counts", {})
            if isinstance(counts, dict) and cached.get("signature") == _caption_signature(journal):
                return counts
        except Exception:  # noqa: BLE001 — rebuild on any cache error
            pass

    by_hash: dict[str, set] = defaultdict(set)
    for srt in journal.rglob("captions/*.srt"):
        by_hash[md5_file(srt)].add(srt.parent.parent)
    counts = {h: len(items) for h, items in by_hash.items() if len(items) > 1}

    if use_cache:
        try:
            cache_path.write_text(
                json.dumps({"signature": _caption_signature(journal), "counts": counts}),
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001 — cache is best-effort
            pass
    return counts


def main() -> int:
    args = parse_args(sys.argv[1:])
    api_key = load_api_key()
    base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    langs = args.lang or TARGET_LANGS

    cap_files = iter_caption_files(args.journal, args.series)
    if args.skip_to:
        cap_files = cap_files[args.skip_to - 1 :]
    if args.limit:
        cap_files = cap_files[: args.limit]

    # Skip caption files whose exact bytes are duplicated across multiple items —
    # these are copied placeholders, not real per-video source.
    placeholder_counts = build_placeholder_hashes(args.journal)
    if placeholder_counts:
        real_files = [srt for srt in cap_files if md5_file(srt) not in placeholder_counts]
        placeholders = [srt for srt in cap_files if md5_file(srt) in placeholder_counts]
    else:
        real_files, placeholders = cap_files, []

    print(f"journal={args.journal}")
    print(
        f"series={args.series or '(all)'}  langs={langs}  model={args.model}  "
        f"caption_files={len(cap_files)}  batch={args.batch}  workers={args.workers}  force={args.force}"
    )
    if placeholder_counts:
        print(
            f"  skipped {len(placeholders)} duplicate/placeholder caption files "
            f"(content shared across >1 item); {len(real_files)} real files to translate"
        )
    if not real_files:
        print("No caption files matched.")
        return 0 if placeholders else 1

    produced = 0
    skipped = 0
    falls = 0
    started = time.time()
    for idx, srt in enumerate(real_files, 1):
        item_dir = srt.parent.parent
        trans_dir = item_dir / "translations"
        for lang in langs:
            dest_name = translation_filename(srt, lang)
            if existing_translation(item_dir, dest_name) and not args.force:
                skipped += 1
                continue
            src_text = srt.read_text(encoding="utf-8-sig", errors="replace")
            try:
                translated, failed, ncue = translate_srt(
                    src_text, lang, args.model, api_key, base_url, args.batch, args.workers
                )
            except Exception as e:
                print(f"  ! {srt.name[:40]} [{lang}] ERROR: {e}")
                falls += 1
                continue
            trans_dir.mkdir(parents=True, exist_ok=True)
            (trans_dir / dest_name).write_text(translated, encoding="utf-8")
            produced += 1
            falls += failed
            if failed:
                print(f"  ~ {srt.name[:40]} [{lang}] {failed} batch(es) fell back")
        if idx % 3 == 0:
            el = time.time() - started
            print(
                f"  …{idx}/{len(cap_files)} files  (+{produced} produced, {skipped} skipped)  {el:.0f}s"
            )
    el = time.time() - started
    print(
        f"\nDone. Produced {produced} translation files, skipped {skipped} existing, "
        f"{falls} fallback batch(es), in {el:.0f}s."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
