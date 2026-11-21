"""
Event categorization for Active Inference Journal streams.

This module handles pattern matching to categorize video events
by type, series, and episode number.
"""

import re
from dataclasses import dataclass


@dataclass
class EventCategory:
    """Categorized event information."""

    category: str | None = None
    series: str | None = None
    episode: str | None = None


# Pattern definitions for different stream types
UNIQUE_EVENT_PATTERNS = {
    "livestream": r"(Livestream) #?(\d+)\.(\d+)",
    "modelstream": r"(ModelStream) #?(\d+)\.(\d+)",
    "gueststream": r"(GuestStream) #?(\d+)\.(\d+)",
    "insights": r"Insights #(\d+)",
    "roundtable": r"(Roundtable) ?(\d+)\.(\d+)",
    "mathstream": r"MathStream #(\d+)\.(\d+)",
    "orgstream": r"OrgStream #?(\d+)\.(\d+)",
    "morphstream": r"MorphStream #?(\d+)\.(\d+)",
    "artstream": r"ArtStream #?(\d+)\.(\d+)",
    "mathartstream": r"MathArtStream (\d+)",
    "activeinferantstream": r"Active InferAnt Stream #?(\d+)\.(\d+)",
    "textbookgroup": r"ActInf Textbook Group ~ Cohort (\d+) ~ Meeting (\d+)",
    "textbook_parr": r"Parr, Pezzulo, Friston 2022 Textbook Cohort (\d+), Meeting (\d+)",
    "symposium_2021": r"Prof\. Karl Friston ~ Applied Active Inference Symposium",
    "symposium_2022": r"2nd Applied Active Inference Symposium",
    "symposium": r"Applied Active Inference Symposium (\d{4}) part (\d+)",
    "bookstream": r"(Active Inference)? ?(?:~.*~)? ?BookStream #?(\d+)\.(\d+)",
    "social_sciences": r"(Active Inference for (?:the )?Social Sciences 2023|ActInf Social Sciences 2023)",
    "physics_info": r"Physics as Information Processing",
    "reviewstream": r"(ReviewStream|Active Inference Livestream Review)",
    "twitterspaces": r"Active Inference ~ Twitter spaces #(\d+)",
}

YOUTUBE_TITLE_PATTERNS = {
    "symposium_2021": r"Prof\. Karl Friston ~ Applied Active Inference Symposium",
    "symposium_2022": r"2nd Applied Active Inference Symposium",
    "symposium_ordinal": r"(\d+)(?:st|nd|rd|th) Applied Active Inference Symposium \(Part (\d+)",
    "symposium_day": (
        r"\b\d+(?:st|nd|rd|th) Applied Active Inference Symposium "
        r"\(Day (?P<day>[1-9]\d*), [A-Za-z]+ \d{1,2}, (?P<year>20\d{2})\)"
    ),
    "bookstream": r"(Active Inference)? ?(?:~.*~)? ?BookStream #?(\d+)\.(\d+)",
    "social_sciences": r"(Active Inference for (?:the )?Social Sciences 2023|ActInf Social Sciences 2023)",
    "physics_info": r"Physics as Information Processing",
    "gueststream": r"(ActInf|Active Inference) GuestStream #?(\d+)\.(\d+)",
    "insights": r"Active Inference Insights (\d+)",
    "livestream": r"(ActInf|Active Inference) (?:Livestream|LiveStream) #?(\d+)\.(\d+)",
    "mathstream": r"ActInf MathStream (\d+)\.(\d+)",
    "modelstream": r"(ActInf|Active Inference) ModelStream #?(\d+)\.(\d+)",
    "orgstream": r"ActInf OrgStream #?(\d+)\.(\d+)",
    "reviewstream": r"(ReviewStream|Active Inference Livestream Review)",
    "roundtable": r"(ActInfLab|Active Inference Institute).*?(\d{4}).*?Quarterly Roundtable #(\d+)",
    "textbookgroup": r"ActInf Textbook Group ~ Cohort (\d+) ~ (?:Meeting|Session) (\d+)",
    "fundamentals": r"Fundamentals of Active Inference.*?Session (\d+)",
    "twitterspaces": r"Active Inference ~ Twitter spaces #(\d+)",
    "morphstream": r"MorphStream #?(\d+)\.(\d+)",
    "artstream": r"ArtStream #?(\d+)\.(\d+)",
    "mathartstream": r"MathArtStream (\d+)",
    "activeinferantstream": r"Active InferAnt Stream #?(\d+)\.(\d+)",
}


def categorize_name(
    name: str, is_unique_event_name: bool = True
) -> tuple[str | None, str | None, str | None]:
    """
    Categorize an event name by extracting category, series, and episode.

    Args:
        name: The event name to categorize
        is_unique_event_name: True if using unique event name from Coda table,
                             False if using YouTube video title

    Returns:
        Tuple of (category, series, episode)
    """
    patterns = UNIQUE_EVENT_PATTERNS if is_unique_event_name else YOUTUBE_TITLE_PATTERNS

    # Try matching each pattern type
    result = _match_symposium(name, patterns)
    if result.category:
        return result.category, result.series, result.episode

    result = _match_bookstream(name, patterns)
    if result.category:
        return result.category, result.series, result.episode

    result = _match_course(name, patterns)
    if result.category:
        return result.category, result.series, result.episode

    result = _match_stream(name, patterns, is_unique_event_name)
    if result.category:
        return result.category, result.series, result.episode

    result = _match_textbook(name, patterns)
    if result.category:
        return result.category, result.series, result.episode

    result = _match_other(name, patterns)
    if result.category:
        return result.category, result.series, result.episode

    # No match found
    # logger.debug("match not found for %s", name)
    return None, None, None


def _match_symposium(name: str, patterns: dict) -> EventCategory:
    """Match symposium patterns."""
    result = EventCategory()

    if day_pattern := patterns.get("symposium_day"):
        match = re.search(day_pattern, name)
        if match:
            return EventCategory(
                category=f"Applied Active Inference Symposium/{match['year']}",
                series=f"Day {match['day']}",
            )

    if "symposium" in patterns:
        match = re.search(patterns["symposium"], name)
        if match:
            result.category = f"Applied Active Inference Symposium/{match.group(1)}"
            result.series = f"part {match.group(2)}"
            return result

    # "Nth Applied Active Inference Symposium (Part P, ...)" — the 3rd (2023)
    # onward use ordinal titles; 1st/2021 and 2nd/2022 keep their bespoke rules.
    if "symposium_ordinal" in patterns:
        match = re.search(patterns["symposium_ordinal"], name)
        if match and int(match.group(1)) >= 3:
            result.category = f"Applied Active Inference Symposium/{2020 + int(match.group(1))}"
            result.series = f"part {match.group(2)}"
            return result

    if "symposium_2021" in patterns:
        match = re.search(patterns["symposium_2021"], name)
        if match:
            result.category = "Applied Active Inference Symposium"
            result.series = "2021 Symposium with Karl Friston"
            return result

    if "symposium_2022" in patterns:
        match = re.search(patterns["symposium_2022"], name)
        if match:
            result.category = "Applied Active Inference Symposium"
            result.series = "2022 Symposium on Robotics"
            return result

    return result


def _match_bookstream(name: str, patterns: dict) -> EventCategory:
    """Match bookstream patterns."""
    result = EventCategory()

    if "bookstream" in patterns:
        match = re.search(patterns["bookstream"], name)
        if match:
            result.category = "BookStream"
            result.series = f"BookStream_{match.group(2).zfill(3)}"
            result.episode = match.group(3)
            return result

    return result


def _match_course(name: str, patterns: dict) -> EventCategory:
    """Match course patterns."""
    result = EventCategory()

    if "social_sciences" in patterns:
        match = re.search(patterns["social_sciences"], name)
        if match:
            result.category = "Courses/ActiveInferenceForTheSocialSciences"
            return result

    if "physics_info" in patterns:
        match = re.search(patterns["physics_info"], name)
        if match:
            result.category = "Courses/PhysicsAsInformationProcessing_ChrisFields"
            return result

    return result


def _match_stream(name: str, patterns: dict, is_unique_event_name: bool) -> EventCategory:
    """Match various stream patterns."""
    result = EventCategory()

    # Streams with series.episode format
    stream_types = [
        ("gueststream", "GuestStream", 2, 3),
        ("livestream", "Livestream", 2, 3),
        ("modelstream", "ModelStream", 2, 3),
        ("mathstream", "MathStream", 1, 2),
        ("orgstream", "OrgStream", 1, 2),
        ("morphstream", "MorphStream", 1, 2),
        ("artstream", "ArtStream", 1, 2),
        ("activeinferantstream", "ActiveInferAntStream", 1, 2),
    ]

    for pattern_key, category_name, series_group, episode_group in stream_types:
        if pattern_key in patterns:
            match = re.search(patterns[pattern_key], name)
            if match:
                result.category = category_name
                result.series = f"{category_name}_{match.group(series_group).zfill(3)}"
                result.episode = (
                    match.group(episode_group) if episode_group <= len(match.groups()) else None
                )
                return result

    # Insights (series only)
    if "insights" in patterns:
        match = re.search(patterns["insights"], name)
        if match:
            result.category = "Insights"
            result.series = f"Insights_{match.group(1).zfill(3)}"
            return result

    # MathArtStream (no episode)
    if "mathartstream" in patterns:
        match = re.search(patterns["mathartstream"], name)
        if match:
            result.category = "MathArtStream"
            result.series = f"MathArtStream_{match.group(1).zfill(3)}"
            return result

    # ReviewStream (no series/episode)
    if "reviewstream" in patterns:
        match = re.search(patterns["reviewstream"], name)
        if match:
            result.category = "ReviewStream"
            return result

    # Roundtable
    if "roundtable" in patterns:
        match = re.search(patterns["roundtable"], name)
        if match:
            result.category = "Roundtable"
            # Both roundtable patterns always carry >=3 groups (year, number);
            # the older else-branch was unreachable and is removed.
            result.series = f"Roundtable_{match.group(2)}.{match.group(3)}"
            return result

    return result


def _match_textbook(name: str, patterns: dict) -> EventCategory:
    """Match textbook group patterns."""
    result = EventCategory()

    # Namjoshi 2026 "Fundamentals of Active Inference" reading group
    if "fundamentals" in patterns:
        match = re.search(patterns["fundamentals"], name)
        if match:
            result.category = "TextbookGroup/Namjoshi2026/Cohort_1"
            result.series = f"Session_{match.group(1).zfill(3)}"
            return result

    if "textbook_parr" in patterns:
        match = re.search(patterns["textbook_parr"], name)
        if match:
            result.category = f"TextbookGroup/ParrPezzuloFriston2022/Cohort_{match.group(1)}"
            result.series = f"Meeting_{match.group(2).zfill(3)}"
            return result

    if "textbookgroup" in patterns:
        match = re.search(patterns["textbookgroup"], name)
        if match:
            result.category = f"TextbookGroup/ParrPezzuloFriston2022/Cohort_{match.group(1)}"
            result.series = f"Meeting_{match.group(2).zfill(3)}"
            return result

    return result


def _match_other(name: str, patterns: dict) -> EventCategory:
    """Match other patterns."""
    result = EventCategory()

    if "twitterspaces" in patterns:
        match = re.search(patterns["twitterspaces"], name)
        if match:
            result.category = "Twitter Spaces"
            result.series = f"TwitterSpaces_{match.group(1).zfill(3)}"
            return result

    return result
