"""Unit test verifying preservation of paper citation/abstract with inserted timestamps."""

from journal_utilities.youtube.metadata_formatter import (
    ChapterEntry,
    assemble_video_description,
    build_journal_item_url,
    split_base_description,
)


def test_paper_abstract_preservation_and_insertion():
    raw_desc = """\"Order and change in art: towards an active inference account of aesthetic experience\"
Sander Van de Cruys, Jacopo Frascaroli and Karl Friston
Published:18 December 2023 https://doi.org/10.1098/rstb.2022.0411
https://royalsocietypublishing.org/doi/10.1098/rstb.2022.0411

How to account for the power that art holds over us? Why do artworks touch us deeply...

Active Inference Institute information:
Website: https://activeinference.org/
Twitter: https://twitter.com/InferenceActive
Discord: https://discord.gg/8VNKNp4jtx
YouTube: https://www.youtube.com/c/ActiveInference/
Active Inference Livestreams: https://coda.io/@active-inference-institute/livestreams"""

    paper_info, link_block = split_base_description(raw_desc)
    assert "Sander Van de Cruys, Jacopo Frascaroli and Karl Friston" in paper_info
    assert "https://doi.org/10.1098/rstb.2022.0411" in paper_info
    assert "Website:" in link_block

    chapters = [
        ChapterEntry(0.0, "Introduction and Welcoming"),
        ChapterEntry(185.0, "The Epistemic Arc"),
    ]

    item_path = "data/video/activeinferenceinstitute/Insights/Insights_001"
    assembled = assemble_video_description(
        base_description=raw_desc,
        chapters=chapters,
        github_transcript_url=build_journal_item_url(item_path),
    )

    # 1. Verify paper information is at the top
    assert assembled.startswith('"Order and change in art')
    assert "https://doi.org/10.1098/rstb.2022.0411" in assembled

    # 2. Verify timestamps are positioned between abstract and links
    abstract_pos = assembled.find("How to account for the power that art holds over us?")
    chapters_pos = assembled.find("--- TIMESTAMPS & CHAPTERS ---")
    resources_pos = assembled.find("--- RESOURCES & TRANSCRIPT ---")
    links_pos = assembled.find("Active Inference Institute information:")
    assert "https://video.activeinference.institute/" in assembled
    assert "https://coda.io" not in assembled

    assert abstract_pos < chapters_pos < resources_pos < links_pos

    # 3. Verify journal transcript link resolves to the item tree, not the dead
    #    blob/main/transcripts/<id>.md path (Y1/E1/I1 regression lock).
    assert (
        "https://github.com/ActiveInferenceInstitute/ActiveInferenceJournal/tree/main/" + item_path
        in assembled
    )
    assert "blob/main/transcripts" not in assembled
