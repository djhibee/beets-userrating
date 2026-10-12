import pytest

from beets.dbcore.query import InvalidQueryArgumentValueError

from beetsplug.userrating.compat import UserError
from beetsplug.userrating.ratings import (
    USER_RATINGS_TYPE, RatingError, UserRatingQuery, UserRatings,
    format_ratings, parse_query_pattern, tokenize)


@pytest.fixture(autouse=True)
def default_user(monkeypatch):
    monkeypatch.setattr(UserRatings, 'default_user', 'djhibee')


@pytest.mark.parametrize('text, expected', [
    ('4', {'djhibee': 4}),
    ('user1: 3', {'user1': 3}),
    ('user1:3', {'user1': 3}),
    ('user1=3', {'user1': 3}),
    ("{'user1':3}", {'user1': 3}),
    ("{'user2':4,'user1': 3}", {'user1': 3, 'user2': 4}),
    ('{"user2": 4, "user1": 3}', {'user1': 3, 'user2': 4}),
    ('user1:3, user2:4', {'user1': 3, 'user2': 4}),
    ('user1:3; user2:4', {'user1': 3, 'user2': 4}),
    ('user1:0', {'user1': 0}),
    ('user1:none, user2:1', {'user2': 1}),
    ("{'user1': None}", {}),
    ('', {}),
])
def test_parse_human_formats(text, expected):
    assert UserRatings(text) == expected


def test_parse_numbers_and_mappings():
    assert UserRatings(7) == {'djhibee': 7}
    assert UserRatings(7.0) == {'djhibee': 7}
    assert UserRatings({'toto': '3'}) == {'toto': 3}


@pytest.mark.parametrize('text', [
    '11', '-1', '3.5', 'user1:abc', "{'user1': 'x'}", '{bad', 'bad user:3',
    "{'12': 3}", '[1, 2]',
])
def test_parse_invalid(text):
    with pytest.raises(RatingError):
        UserRatings(text)


def test_null_rating_differs_from_zero():
    ratings = UserRatings('toto:0')
    assert ratings.get('toto') == 0
    assert ratings.get('titi') is None
    assert 'toto' in ratings and 'titi' not in ratings


def test_format_roundtrip():
    ratings = UserRatings({'toto': 3, 'djhibee': 0})
    assert str(ratings) == 'djhibee:0, toto:3'
    assert UserRatings(str(ratings)) == ratings
    assert format_ratings(ratings, ['toto']) == 'toto:3'
    assert format_ratings(UserRatings()) == ''


def test_tokenize_user_only():
    assert tokenize('toto') == [('toto', None)]
    assert tokenize('3..5') == [(None, '3..5')]


def test_type_format_shows_default_user():
    assert USER_RATINGS_TYPE.format(UserRatings('djhibee:4, toto:2')) == '4'
    assert USER_RATINGS_TYPE.format(UserRatings('toto:2')) == ''
    assert USER_RATINGS_TYPE.format(UserRatings('djhibee:0')) == '0'
    assert USER_RATINGS_TYPE.format(None) == ''


def test_type_sql_roundtrip_and_legacy_values():
    ratings = UserRatings('djhibee:4, toto:0')
    sql = USER_RATINGS_TYPE.to_sql(ratings)
    assert USER_RATINGS_TYPE.from_sql(sql) == ratings
    assert USER_RATINGS_TYPE.from_sql(None) == {}
    # integer values stored by previous versions of the plugin
    assert USER_RATINGS_TYPE.from_sql('8') == {'djhibee': 8}
    assert USER_RATINGS_TYPE.from_sql(8) == {'djhibee': 8}
    assert USER_RATINGS_TYPE.from_sql('garbage value') == {}


def test_type_parse_raises_user_error():
    assert USER_RATINGS_TYPE.parse("{'toto': 3}") == {'toto': 3}
    with pytest.raises(UserError):
        USER_RATINGS_TYPE.parse('42')


def test_sorting_by_default_user():
    values = [UserRatings('djhibee:5'), UserRatings(), UserRatings('2')]
    assert [v.default for v in sorted(values)] == [None, 2, 5]


@pytest.mark.parametrize('pattern, value, expected', [
    ('4', 'djhibee:4', True),
    ('4', 'toto:4', False),
    ('user1: 3', 'user1:3, user2:4', True),
    ('user1:3', 'user1:4', False),
    ("{'user2':4,'user1': 3}", 'user1:3, user2:4', True),
    ("{'user2':4,'user1': 3}", 'user1:3, user2:5', False),
    ('3..5', 'djhibee:4', True),
    ('3..5', 'djhibee:6', False),
    ('toto:..2', 'toto:0', True),
    ('toto:8..', 'toto:7', False),
    ('toto', 'toto:0', True),
    ('toto', 'djhibee:1', False),
    ('toto:none', 'djhibee:1', True),
    ('toto:none', 'toto:0', False),
    ('', 'toto:0', True),
    ('', None, False),
    ('0', None, False),
])
def test_query(pattern, value, expected):
    query = UserRatingQuery('userrating', pattern)
    assert UserRatingQuery.value_match(pattern, value) is expected
    assert query._match(query.conditions, value) is expected


def test_query_invalid_pattern():
    with pytest.raises(InvalidQueryArgumentValueError):
        UserRatingQuery('userrating', 'toto:42')


def test_parse_query_pattern_default_user():
    conditions = parse_query_pattern('5')
    assert list(conditions) == ['djhibee']
