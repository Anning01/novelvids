import pytest

from exceptions.remake import RemakeError
from services.remake.episodes import parse_episode_number, validate_episode_batch


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("第12集.mp4", 12),
        ("第 003 话.mov", 3),
        ("Drama EP0012.mp4", 12),
        ("Drama e07.mov", 7),
        ("12集.mp4", 12),
        ("第1集_EP1.mp4", 1),
    ],
)
def test_parse_episode_number_supports_all_contract_patterns(filename, expected):
    assert parse_episode_number(filename) == expected


@pytest.mark.parametrize("filename", ["花絮.mp4", "第0集.mp4", "EP100000.mov"])
def test_parse_episode_number_rejects_missing_or_out_of_range(filename):
    with pytest.raises(RemakeError) as caught:
        parse_episode_number(filename)
    assert caught.value.error_code == "REMAKE_EPISODE_MISSING"


def test_parse_episode_number_rejects_distinct_matches_as_ambiguous():
    with pytest.raises(RemakeError) as caught:
        parse_episode_number("第1集_EP2.mp4")
    assert caught.value.error_code == "REMAKE_EPISODE_AMBIGUOUS"
    assert caught.value.context["episode_numbers"] == [1, 2]


def test_validate_episode_batch_sorts_warns_about_gaps_and_checks_claims():
    items, missing = validate_episode_batch([
        ("第3集.mp4", 3, "token-3"),
        ("第1集.mov", 1, "token-1"),
    ])
    assert [item.episode_number for item in items] == [1, 3]
    assert [item.value for item in items] == ["token-1", "token-3"]
    assert missing == [2]

    with pytest.raises(RemakeError) as mismatch:
        validate_episode_batch([("第2集.mp4", 3, "token")])
    assert mismatch.value.error_code == "REMAKE_SOURCE_MODE_MISMATCH"


def test_validate_episode_batch_rejects_duplicate_episode_numbers():
    with pytest.raises(RemakeError) as caught:
        validate_episode_batch([
            ("第1集.mp4", 1, "token-1"),
            ("EP01.mov", 1, "token-2"),
        ])
    assert caught.value.error_code == "REMAKE_EPISODE_DUPLICATED"
    assert caught.value.status_code == 409
