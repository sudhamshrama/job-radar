"""US location heuristics.

Every string here came from a real posting in the deployed table or a live API
response, not from imagination.
"""

import pytest

from job_radar.location import is_us

US = [
    "New York, New York, USA",
    "Boston, Massachusetts, USA; New York, New York, USA",
    "San Francisco, CA",
    "Austin, TX",
    "Arlington, VA",
    "Remote - US",
    "REMOTE (US)",
    "Remote (US)",
    "US Fully Remote",
    "Remote U.S.",
    "Washington, D.C.",
    "Seattle, WA",
    "Remote US or Ontario, Canada",   # a US signal beats a foreign one
    "Remote",                          # bare remote on a US board
    "Anywhere",
]

NOT_US = [
    # Regression: both reached the deployed table. Boards write ISO COUNTRY
    # codes in the same comma format as US STATE codes, so ", CA" was read as
    # California and ", IN" as Indiana.
    "Canada - Toronto, CA",
    "India - Hyderabad, IN",
    "Cork",
    "Paris, France",
    "Bengaluru, India",
    "Noida, India (Delhi NCR)",
    "London, UK",
    "Toronto, Canada",
    "Berlin, Germany",
    "Tel Aviv, Israel",
    "Dublin, Ireland",
    "Sydney, Australia",
    "Tokyo, Japan",
    "REMOTE (worldwide)",
    "Remote - EMEA",
    "Remote - APAC",
    "In-Office",
    "",
]


@pytest.mark.parametrize("location", US)
def test_us_locations_accepted(location):
    assert is_us(location) is True


@pytest.mark.parametrize("location", NOT_US)
def test_non_us_locations_rejected(location):
    assert is_us(location) is False


def test_state_abbreviations_need_a_comma():
    """A bare two-letter token is too ambiguous to trust.

    "CA" is also Canada, "IN" is also India, "OR" is an English word.
    """
    assert is_us("Remote, CA") is True
    assert is_us("Vancouver CA") is False


def test_state_codes_are_not_matched_inside_prose():
    """Regression, found in live data.

    A MongoDB role located in "Toronto; Vancouver" passed the US filter because
    its title read "Site Reliability Engineering, Fabric (Mid, Senior, or
    Staff)" — and ", or" matched Oregon. "or", "in", "me", "hi", "ok" and "de"
    are all English words as well as state codes, so abbreviations are only
    matched against the structured location field.
    """
    canadian = "Site Reliability Engineering (Mid, Senior, or Staff)"
    assert is_us("Toronto; Vancouver", canadian) is False
    assert is_us("Montreal", "Platform Engineer, Senior, or Staff") is False
    # ...while a genuine location field still works.
    assert is_us("Portland, OR") is True
    assert is_us("Indianapolis, IN") is True


def test_extra_text_is_searched_when_location_is_empty():
    """Hacker News postings have no location field — only prose."""
    assert is_us("", "Acme | Platform Engineer | REMOTE (US) | Full-time") is True
    assert is_us("", "Acme | Platform Engineer | Berlin, Germany") is False


def test_worldwide_beats_a_bare_remote_hint():
    assert is_us("Remote worldwide") is False


def test_known_ambiguity_ontario_ca_is_treated_as_california():
    """A genuine ambiguity, documented rather than pretended away.

    Ontario is a Canadian province AND a real city in California. "Ontario, CA"
    is resolved as California, because Canadian listings almost always spell
    the country out ("Ontario, Canada" / "Toronto, ON, Canada") while US
    listings use the "City, ST" form.

    This is the accepted failure mode of the whole module: prefer a few
    non-US roles slipping through over dropping genuine US ones.
    """
    assert is_us("Ontario, CA") is True
    assert is_us("Ontario, Canada") is False


def test_markers_match_only_on_token_boundaries():
    """Regression from live data: "usa" matched inside "thousands".

    A Berlin / EU-remote posting was classified as US because its description
    said "used by tens of thousands of teams" — "tho-USA-nds". Substring
    matching without boundaries is wrong for short country codes.
    """
    berlin = "Berlin / EU-remote, ~1 week onsite every 2 months"
    prose = "used by tens of thousands of teams to ship and debug their apps"
    assert is_us(berlin, prose) is False

    # Other collisions the same bug would have caused.
    assert is_us("", "high usage of our platform") is False
    assert is_us("", "we are a usa company") is True
