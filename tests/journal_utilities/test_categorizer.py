"""
Test suite for the categorizer module.

These tests verify pattern matching for all stream types.
"""

from journal_utilities.youtube.categorizer import categorize_name


class TestCategorizeName:
    """Tests for categorize_name function."""

    # Livestream tests
    def test_fundamentals_session(self):
        category, series, episode = categorize_name(
            "Fundamentals of Active Inference (Chapter 6 Session 27) July 14, 2026", False
        )
        assert category == "TextbookGroup/Namjoshi2026/Cohort_1"
        assert series == "Session_027"

    def test_fundamentals_review_session(self):
        category, series, _ = categorize_name(
            "Fundamentals of Active Inference (Part 1 review, Session 24) July 3, 2026", False
        )
        assert category == "TextbookGroup/Namjoshi2026/Cohort_1"
        assert series == "Session_024"

    def test_livestream_unique_event_name(self):
        category, series, episode = categorize_name("Livestream #057.2", True)
        assert category == "Livestream"
        assert series == "Livestream_057"
        assert episode == "2"

    def test_livestream_youtube_title(self):
        category, series, episode = categorize_name("ActInf Livestream #057.2", False)
        assert category == "Livestream"
        assert series == "Livestream_057"
        assert episode == "2"

    def test_livestream_active_inference_prefix(self):
        category, series, episode = categorize_name("Active Inference LiveStream #012.1", False)
        assert category == "Livestream"
        assert series == "Livestream_012"
        assert episode == "1"

    # GuestStream tests
    def test_gueststream_unique_event_name(self):
        category, series, episode = categorize_name("GuestStream #003.1", True)
        assert category == "GuestStream"
        assert series == "GuestStream_003"
        assert episode == "1"

    def test_gueststream_youtube_title(self):
        category, series, episode = categorize_name("Active Inference GuestStream #003.1", False)
        assert category == "GuestStream"
        assert series == "GuestStream_003"
        assert episode == "1"

    # ModelStream tests
    def test_modelstream_unique_event_name(self):
        category, series, episode = categorize_name("ModelStream #005.2", True)
        assert category == "ModelStream"
        assert series == "ModelStream_005"
        assert episode == "2"

    def test_modelstream_youtube_title(self):
        category, series, episode = categorize_name("ActInf ModelStream #005.2", False)
        assert category == "ModelStream"
        assert series == "ModelStream_005"
        assert episode == "2"

    # MathStream tests
    def test_mathstream_unique_event_name(self):
        category, series, episode = categorize_name("MathStream #001.3", True)
        assert category == "MathStream"
        assert series == "MathStream_001"
        assert episode == "3"

    def test_mathstream_youtube_title(self):
        category, series, episode = categorize_name("ActInf MathStream 001.3", False)
        assert category == "MathStream"
        assert series == "MathStream_001"
        assert episode == "3"

    # OrgStream tests
    def test_orgstream_unique_event_name(self):
        category, series, episode = categorize_name("OrgStream #002.1", True)
        assert category == "OrgStream"
        assert series == "OrgStream_002"
        assert episode == "1"

    # Insights tests
    def test_insights_unique_event_name(self):
        category, series, episode = categorize_name("Insights #42", True)
        assert category == "Insights"
        assert series == "Insights_042"
        assert episode is None

    def test_insights_youtube_title(self):
        category, series, episode = categorize_name("Active Inference Insights 42", False)
        assert category == "Insights"
        assert series == "Insights_042"
        assert episode is None

    # BookStream tests
    def test_bookstream_unique_event_name(self):
        category, series, episode = categorize_name("BookStream #001.2", True)
        assert category == "BookStream"
        assert series == "BookStream_001"
        assert episode == "2"

    def test_bookstream_with_prefix(self):
        category, series, episode = categorize_name(
            "Active Inference ~ Some Book ~ BookStream #002.3", True
        )
        assert category == "BookStream"
        assert series == "BookStream_002"
        assert episode == "3"

    # Symposium tests
    def test_symposium_2021(self):
        category, series, episode = categorize_name(
            "Prof. Karl Friston ~ Applied Active Inference Symposium", True
        )
        assert category == "Applied Active Inference Symposium"
        assert series == "2021 Symposium with Karl Friston"
        assert episode is None

    def test_symposium_2022(self):
        category, series, episode = categorize_name("2nd Applied Active Inference Symposium", True)
        assert category == "Applied Active Inference Symposium"
        assert series == "2022 Symposium on Robotics"
        assert episode is None

    def test_symposium_ordinal_2025(self):
        category, series, _ = categorize_name(
            "5th Applied Active Inference Symposium (Part 2, Nov 13, 2025) ~ (Full reupload)", False
        )
        assert category == "Applied Active Inference Symposium/2025"
        assert series == "part 2"

    def test_symposium_ordinal_2024(self):
        category, series, _ = categorize_name(
            "4th Applied Active Inference Symposium (Part 1, Nov 13, 2024) ~ Full Upload", False
        )
        assert category == "Applied Active Inference Symposium/2024"
        assert series == "part 1"

    # Special patterns tests
    def test_social_sciences(self):
        category, series, episode = categorize_name(
            "Active Inference for the Social Sciences 2023", True
        )
        assert category == "Courses/ActiveInferenceForTheSocialSciences"

    def test_physics_info(self):
        category, series, episode = categorize_name(
            "Physics as Information Processing Lecture 1", True
        )
        assert category == "Courses/PhysicsAsInformationProcessing_ChrisFields"

    # Textbook group tests
    def test_textbookgroup(self):
        category, series, episode = categorize_name(
            "ActInf Textbook Group ~ Cohort 5 ~ Meeting 10", True
        )
        assert category == "TextbookGroup/ParrPezzuloFriston2022/Cohort_5"
        assert series == "Meeting_010"
        assert episode is None

    def test_textbook_parr(self):
        category, series, episode = categorize_name(
            "Parr, Pezzulo, Friston 2022 Textbook Cohort 7, Meeting 3", True
        )
        assert category == "TextbookGroup/ParrPezzuloFriston2022/Cohort_7"
        assert series == "Meeting_003"
        assert episode is None

    # Twitter Spaces tests
    def test_twitterspaces(self):
        category, series, episode = categorize_name("Active Inference ~ Twitter spaces #5", True)
        assert category == "Twitter Spaces"
        assert series == "TwitterSpaces_005"
        assert episode is None

    # ReviewStream tests
    def test_reviewstream(self):
        category, series, episode = categorize_name("ReviewStream", True)
        assert category == "ReviewStream"

    def test_reviewstream_alt(self):
        category, series, episode = categorize_name("Active Inference Livestream Review", True)
        assert category == "ReviewStream"

    # Edge cases
    def test_no_match(self):
        category, series, episode = categorize_name("Random Event Name", True)
        assert category is None
        assert series is None
        assert episode is None

    def test_empty_string(self):
        category, series, episode = categorize_name("", True)
        assert category is None
        assert series is None
        assert episode is None

    # MorphStream, ArtStream, MathArtStream tests
    def test_morphstream(self):
        category, series, episode = categorize_name("MorphStream #001.2", True)
        assert category == "MorphStream"
        assert series == "MorphStream_001"
        assert episode == "2"

    def test_artstream(self):
        category, series, episode = categorize_name("ArtStream #003.1", True)
        assert category == "ArtStream"
        assert series == "ArtStream_003"
        assert episode == "1"

    def test_mathartstream(self):
        category, series, episode = categorize_name("MathArtStream 5", True)
        assert category == "MathArtStream"
        assert series == "MathArtStream_005"
        assert episode is None

    # Active InferAnt Stream tests
    def test_activeinferantstream(self):
        category, series, episode = categorize_name("Active InferAnt Stream #002.1", True)
        assert category == "ActiveInferAntStream"
        assert series == "ActiveInferAntStream_002"
        assert episode == "1"
