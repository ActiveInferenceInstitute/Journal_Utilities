"""Tests for journal_utilities.utils.naming."""

from journal_utilities.utils.naming import slugify_title


class TestSlugifyTitle:
    def test_basic(self):
        assert (
            slugify_title("Introduction to recording & livestreaming with OBS")
            == "Introduction_to_recording_and_livestreaming_with_OBS"
        )

    def test_accents_fold(self):
        assert (
            slugify_title("Inês Hipólito: “Dysfunctional Markov Blankets“")
            == "Ines_Hipolito_Dysfunctional_Markov_Blankets"
        )

    def test_length_cap_on_word_boundary(self):
        slug = slugify_title("A" + " very" * 30 + " long title")
        assert len(slug) <= 60
        assert not slug.endswith("_")

    def test_single_long_token_does_not_collapse_to_empty(self):
        # A single 60+ char token with no underscore must not produce an empty
        # slug (both the <=60 and word-boundary cases must hold).
        slug = slugify_title("x" * 80)
        assert slug
        assert len(slug) <= 60

    def test_long_token_padded_with_underscore_cuts_on_word_boundary(self):
        slug = slugify_title("intro_to_" + "y" * 70)
        # Cuts at the boundary before the long unbroken token rather than ""
        assert slug == "intro_to"
        assert len(slug) <= 60

    def test_deterministic(self):
        title = 'Karl Friston "Active inference and deep temporal models" 23.09.19'
        assert slugify_title(title) == slugify_title(title)

    def test_empty_and_symbol_only(self):
        assert slugify_title("") == ""
        assert slugify_title("~ ~ ~") == ""
