#!/usr/bin/env python3
"""
Patch WhisperX for compatibility with pyannote.audio 4.0+

This script updates WhisperX's diarization and VAD modules to use the 'token'
parameter instead of the deprecated 'use_auth_token' parameter.
"""

import sys
from pathlib import Path


def find_whisperx_path() -> Path:
    """Find the installed WhisperX package path."""
    try:
        import whisperx

        whisperx_path = Path(whisperx.__file__).parent
        return whisperx_path
    except ImportError:
        print("Error: WhisperX is not installed.")
        sys.exit(1)


def patch_file(file_path: Path, replacements: list[tuple[str, str]]) -> bool:
    """Apply text replacements to a file."""
    if not file_path.exists():
        print(f"Warning: {file_path} not found, skipping...")
        return False

    content = file_path.read_text()
    original_content = content

    for old, new in replacements:
        content = content.replace(old, new)

    if content != original_content:
        file_path.write_text(content)
        print(f"✓ Patched {file_path.name}")
        return True
    else:
        print(f"- {file_path.name} already patched or no changes needed")
        return False


def main() -> int:
    print("WhisperX Compatibility Patcher")
    print("=" * 50)

    whisperx_path = find_whisperx_path()
    print(f"WhisperX location: {whisperx_path}\n")

    patches_applied = 0

    # Patch 1: diarize.py
    diarize_file = whisperx_path / "diarize.py"
    diarize_patches = [
        (
            "Pipeline.from_pretrained(model_config, use_auth_token=use_auth_token)",
            "Pipeline.from_pretrained(model_config, token=use_auth_token)",
        ),
        # Fix for pyannote.audio 4.0 DiarizeOutput format
        (
            "        diarize_df = pd.DataFrame(diarization.itertracks(yield_label=True), columns=['segment', 'label', 'speaker'])\n"
            "        diarize_df['start'] = diarize_df['segment'].apply(lambda x: x.start)\n"
            "        diarize_df['end'] = diarize_df['segment'].apply(lambda x: x.end)",
            "        # Handle both old Annotation format and new DiarizeOutput format\n"
            "        if hasattr(diarization, 'itertracks'):\n"
            "            # Old format (Annotation)\n"
            "            annotation = diarization\n"
            "        else:\n"
            "            # New format (DiarizeOutput) - extract the annotation\n"
            "            annotation = diarization.speaker_diarization\n"
            "\n"
            "        diarize_df = pd.DataFrame(annotation.itertracks(yield_label=True), columns=['segment', 'label', 'speaker'])\n"
            "        diarize_df['start'] = diarize_df['segment'].apply(lambda x: x.start)\n"
            "        diarize_df['end'] = diarize_df['segment'].apply(lambda x: x.end)",
        ),
    ]
    if patch_file(diarize_file, diarize_patches):
        patches_applied += 1

    # Patch 2: vads/pyannote.py
    vad_file = whisperx_path / "vads" / "pyannote.py"
    vad_patches = [
        (
            "vad_model = Model.from_pretrained(model_fp, use_auth_token=use_auth_token)",
            "vad_model = Model.from_pretrained(model_fp, token=use_auth_token)",
        ),
        (
            "super().__init__(segmentation=segmentation, fscore=fscore, use_auth_token=use_auth_token, **inference_kwargs)",
            "super().__init__(segmentation=segmentation, fscore=fscore, token=use_auth_token, **inference_kwargs)",
        ),
    ]
    if patch_file(vad_file, vad_patches):
        patches_applied += 1

    # Clear Python cache
    print("\nClearing Python cache files...")
    for pyc_file in whisperx_path.rglob("*.pyc"):
        pyc_file.unlink()
    for pycache_dir in whisperx_path.rglob("__pycache__"):
        if pycache_dir.is_dir():
            # rmdir() raises on non-empty dirs (stray .pyo/etc.) and would crash
            # the whole patch mid-run; rmtree(ignore_errors=True) is robust.
            import shutil

            shutil.rmtree(pycache_dir, ignore_errors=True)

    print("\n" + "=" * 50)
    if patches_applied > 0:
        print(f"✓ Successfully applied {patches_applied} patch(es)")
        print("WhisperX is now compatible with pyannote.audio 4.0+")
    else:
        print("No patches needed - WhisperX is already compatible")

    return 0


if __name__ == "__main__":
    sys.exit(main())
