"""Deciding whether a posting is in the United States.

Location strings from job boards are free text and wildly inconsistent:

    "New York, New York, USA"        "Remote - US"
    "San Francisco, CA"              "REMOTE (worldwide)"
    "Paris, France"                  "Bengaluru, India"
    "In-Office"                      ""
    "Remote US or Ontario, Canada"   "London, UK"

There is no country field to rely on, so this is deliberate heuristics with
the failure modes chosen on purpose.

Decision order, and why
-----------------------
1. An explicit US marker wins outright. "Remote - US or Canada" is a role a
   US-based applicant can take, so a US signal beats a foreign one rather than
   being cancelled by it.
2. Otherwise, a foreign marker rejects.
3. Otherwise, a bare remote hint ("Remote", "Anywhere") is ACCEPTED. Most
   postings on US company boards that say only "Remote" are US-eligible, and
   rejecting them loses real roles.
4. Anything else — including empty — is rejected, because "unknown" is not
   "United States".

The tuned failure mode is a small number of worldwide-remote roles slipping
through, rather than dropping genuine US roles. A job board that hides real
matches is worse than one showing a few extras.

State abbreviations are matched only when comma-preceded (", CA") because bare
two-letter tokens collide badly — "CA" is also Canada, "IN" is also India,
"OR" is an English word.
"""

from __future__ import annotations

import re

US_WORDS = [
    "united states", "usa", "u.s.a", "u.s.", "us-based", "us based",
    "us remote", "remote us", "remote - us", "remote, us", "remote (us",
    "us only", "united states of america", "nationwide", "anywhere in the us",
]

US_STATES = [
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming",
    "district of columbia", "washington dc", "washington, d.c",
]

US_CITIES = [
    "san francisco", "new york city", "nyc", "seattle", "austin", "boston",
    "chicago", "denver", "los angeles", "san diego", "san jose", "palo alto",
    "mountain view", "sunnyvale", "santa clara", "menlo park", "cupertino",
    "bellevue", "redmond", "atlanta", "miami", "dallas", "houston", "phoenix",
    "portland", "philadelphia", "pittsburgh", "detroit", "minneapolis",
    "salt lake city", "boulder", "raleigh", "durham", "charlotte", "nashville",
    "brooklyn", "oakland", "berkeley", "irvine", "sacramento", "columbus",
    "indianapolis", "kansas city", "st. louis", "tampa", "orlando",
    "arlington, va", "reston", "mclean", "bethesda", "cambridge, ma",
]

# Comma-preceded only: ", CA" is a state, a bare "CA" is probably Canada.
US_STATE_ABBR = re.compile(
    r",\s*(a[klrz]|c[aot]|de|fl|ga|hi|i[adln]|k[sy]|la|m[adeinost]|"
    r"n[cdehjmvy]|o[hkr]|pa|ri|s[cd]|t[nx]|ut|v[at]|w[aivy]|dc)\b",
    re.IGNORECASE,
)

NON_US = [
    # countries
    "india", "canada", "united kingdom", "england", "scotland", "wales",
    "ireland", "france", "germany", "spain", "italy", "portugal",
    "netherlands", "belgium", "switzerland", "austria", "poland", "czech",
    "hungary", "romania", "bulgaria", "greece", "sweden", "norway", "denmark",
    "finland", "iceland", "estonia", "latvia", "lithuania", "ukraine",
    "russia", "turkey", "israel", "uae", "united arab emirates", "qatar",
    "saudi", "egypt", "nigeria", "kenya", "ghana", "south africa", "morocco",
    "australia", "new zealand", "japan", "china", "hong kong", "taiwan",
    "singapore", "malaysia", "thailand", "vietnam", "indonesia",
    "philippines", "south korea", "pakistan", "bangladesh", "sri lanka",
    "nepal", "brazil", "mexico", "argentina", "chile", "colombia", "peru",
    "uruguay", "costa rica", "panama", "guatemala", "armenia", "georgia (",
    "serbia", "croatia", "slovakia", "slovenia", "cyprus", "malta",
    "luxembourg", "emea", "apac", "latam",
    # cities that are unambiguous
    "london", "dublin", "paris", "lyon", "berlin", "munich", "hamburg",
    "frankfurt", "amsterdam", "rotterdam", "brussels", "zurich", "geneva",
    "vienna", "madrid", "barcelona", "lisbon", "milan", "rome", "warsaw",
    "krakow", "prague", "budapest", "bucharest", "sofia", "athens",
    "stockholm", "oslo", "copenhagen", "helsinki", "tallinn", "kyiv",
    "istanbul", "tel aviv", "dubai", "bangalore", "bengaluru", "mumbai",
    "new delhi", "hyderabad", "chennai", "pune", "noida", "gurgaon",
    "gurugram", "kolkata", "ahmedabad", "toronto", "vancouver", "montreal",
    "ottawa", "calgary", "waterloo, on", "sydney", "melbourne", "brisbane",
    "auckland", "wellington", "tokyo", "osaka", "seoul", "beijing",
    "shanghai", "shenzhen", "taipei", "manila", "jakarta", "bangkok",
    "ho chi minh", "hanoi", "sao paulo", "rio de janeiro", "buenos aires",
    "bogota", "mexico city", "guadalajara", "santiago", "lima", "cairo",
    "lagos", "nairobi", "johannesburg", "cape town",
]

REMOTE_HINT = ["remote", "anywhere", "distributed", "work from home", "wfh"]

WORLDWIDE = ["worldwide", "global", "anywhere in the world", "any country"]


def _has(text: str, needles: list[str]) -> bool:
    """Substring match, but only on whole-token boundaries.

    A plain `needle in text` is wrong here and produced a real false positive:
    a Berlin/EU-remote posting was classified as US because "usa" appears
    inside "thousands" — "tho-USA-nds". Others waiting to happen: "usa" in
    "usage", "india" in "indiana", "oman" in "romania".

    Lookarounds rather than \\b because several markers contain punctuation
    ("u.s.", "remote (us"), where \\b does not behave as expected.
    """
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", text)
        for n in needles
    )


def is_us(location: str, extra_text: str = "") -> bool:
    """True if the posting looks like it is open to a US-based applicant.

    `extra_text` is for sources with no location field — the Hacker News
    normalizer passes the comment body so "REMOTE (US)" buried in prose is
    still found.
    """
    location_text = location.lower().strip()
    text = f"{location} {extra_text}".lower().strip()
    if not text:
        return False

    # 1. Explicit US signal wins, even alongside a foreign one.
    if _has(text, US_WORDS) or _has(text, US_STATES) or _has(text, US_CITIES):
        return True

    # 2. Explicitly worldwide is not "United States".
    if _has(text, WORLDWIDE):
        return False

    # 3. A foreign marker with no US signal rejects.
    #
    # This MUST come before the two-letter state check below. Boards write
    # country codes in exactly the same comma format as state codes:
    #
    #     "Canada - Toronto, CA"    -> ", CA" is Canada, not California
    #     "India - Hyderabad, IN"   -> ", IN" is India, not Indiana
    #
    # Both of those reached the deployed table. A spelled-out country or city
    # name is far stronger evidence than a two-letter code, so it wins.
    if _has(text, NON_US):
        return False

    # 4. Two-letter state codes, against the LOCATION FIELD ONLY — never prose.
    #
    # Also found in live data: a MongoDB role in "Toronto; Vancouver" passed
    # because its TITLE read "...(Mid, Senior, or Staff)" and ", or" matched
    # Oregon. "or", "in", "me", "hi", "ok" and "de" are English words as well
    # as state codes. A structured location field is unambiguous enough for
    # ", OR" to mean Oregon; a sentence is not.
    if US_STATE_ABBR.search(location_text):
        return True

    # 5. Bare "Remote" on a US company board is usually US-eligible.
    if _has(text, REMOTE_HINT):
        return True

    return False
