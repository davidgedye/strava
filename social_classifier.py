"""
Shared classifier for identifying runs done with friends.

Usage:
    from social_classifier import is_with_friends, classify_with_reasons

    is_with_friends(name, description)          # → True / False
    classify_with_reasons(name, description)    # → (bool, list[str])
"""

import re

# Known regular running companions — any mention → social run.
# All matched case-insensitively via \b word boundary.
FRIEND_NAMES = [
    'herve', 'mintu', 'anita', 'tamara', 'lauren',  # original core group
    'chris', 'jonathan', 'jonathon',                 # frequent companions (jonathon = typo variant)
    'grace', 'steve', 'mark', 'martha',              # other regulars
]

# Social signals — (regex_pattern, display_label).
# All applied case-insensitively against the lowercased combined text.
_SOCIAL_PATTERNS = [
    # Expect Delays running group — fuzzy match handles spacing/transposition typos
    (r'expect.{0,3}delay',    'Expect Delays'),
    # "Delays" alone as abbreviated group reference (e.g. 'A Dozen "Delays" for Boxing Day')
    (r'\bdelays\b',           'Expect Delays (abbrev)'),
    # Always Running group — no-space variant (AlwaysRunning) handled by .?
    (r'always.?running',      'Always Running'),
    (r'studio.?runners?',     'Studio Runners'),
    (r'snake2lake',           'Snake2Lake'),
    (r'the frenchman',        'The Frenchman'),     # Herve's nickname
    (r'\bfriends?\b',         'friends'),            # "with friends", "good friends"
    (r'\bcrew\b',             'crew'),               # "with a great crew"
    (r'\b(the )?gang\b',      'the gang'),
    (r'\bmates\b',            'mates'),
]


def _compute_reasons(text, text_lo, has_bean):
    """Core classification logic shared by both public functions."""
    reasons = []

    # ── 1. Explicit friend names ──────────────────────────────────────────────
    for n in FRIEND_NAMES:
        if re.search(r'\b' + n + r'\b', text_lo):
            reasons.append(f'name:{n.capitalize()}')

    # ── 2. Group names / social signals ──────────────────────────────────────
    for pattern, label in _SOCIAL_PATTERNS:
        if re.search(pattern, text_lo):
            reasons.append(label)

    # ── 3. "with/With" + capital letter (proper name) ─────────────────────────
    # Strip "bean" before checking so "With Bean" alone doesn't qualify,
    # but "With Herve and Bean" still does.
    text_for_with = re.sub(r'\bbean\b', '', text, flags=re.I) if has_bean else text
    with_matches = re.findall(r'\b[Ww]ith\s+([A-Z]\w*)', text_for_with)
    if with_matches:
        reasons.append('with+Name: ' + ', '.join(dict.fromkeys(with_matches)))

    return reasons


def is_with_friends(name, desc=''):
    """
    Return True if this run was likely done with other people.

    Rules (applied to name + description combined):
      1. Any mention of a known friend's name → social
      2. Group/social signal match → social
      3. "with"/"With" followed by a capital letter (proper name) → social
      4. Bean exclusion: if "bean" appears but none of the above signals
         fire (after removing "bean") → NOT social.
         Handles "With Bean" dog run but keeps "With Herve and Bean".
    """
    text    = (name or '') + ' ' + (desc or '')
    text_lo = text.lower()
    has_bean = bool(re.search(r'\bbean\b', text_lo))
    reasons = _compute_reasons(text, text_lo, has_bean)
    if not reasons and has_bean:
        return False
    return bool(reasons)


def classify_with_reasons(name, desc=''):
    """
    Like is_with_friends() but returns (bool, list[str]) for reporting/debugging.
    """
    text    = (name or '') + ' ' + (desc or '')
    text_lo = text.lower()
    has_bean = bool(re.search(r'\bbean\b', text_lo))
    reasons = _compute_reasons(text, text_lo, has_bean)
    if not reasons and has_bean:
        return False, ['excluded: Bean']
    return bool(reasons), reasons
