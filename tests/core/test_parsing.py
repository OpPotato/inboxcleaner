import pytest

from inboxcleaner.core.parsing import (
    parse_from_header,
    parse_list_unsubscribe,
    registered_domain,
)


@pytest.mark.parametrize(
    "raw,email,name",
    [
        ('"Uniqlo USA" <news@uniqlo.com>', "news@uniqlo.com", "Uniqlo USA"),
        ("Uniqlo <news@uniqlo.com>", "news@uniqlo.com", "Uniqlo"),
        ("news@uniqlo.com", "news@uniqlo.com", None),
        ("<news@uniqlo.com>", "news@uniqlo.com", None),
        ('"News, from Uniqlo" <news@uniqlo.com>', "news@uniqlo.com", "News, from Uniqlo"),
    ],
)
def test_parse_from_header(raw, email, name):
    assert parse_from_header(raw) == (email, name)


def test_parse_from_header_lowercases_email():
    e, _ = parse_from_header("Uniqlo <NEWS@UNIQLO.COM>")
    assert e == "news@uniqlo.com"


def test_registered_domain():
    assert registered_domain("news@uniqlo.com") == "uniqlo.com"
    assert registered_domain("noreply@email.uniqlo.com") == "uniqlo.com"
    assert registered_domain("a@b.co.uk") == "b.co.uk"


def test_parse_list_unsubscribe_mailto():
    raw = "<mailto:u@x.com?subject=unsubscribe>, <https://x.com/u>"
    actions = parse_list_unsubscribe(raw)
    kinds = {a.kind for a in actions}
    assert kinds == {"mailto", "http"}
    mailto = next(a for a in actions if a.kind == "mailto")
    assert mailto.target == "u@x.com"
    assert mailto.subject == "unsubscribe"


def test_parse_list_unsubscribe_only_http():
    actions = parse_list_unsubscribe("<https://x.com/u?token=abc>")
    assert len(actions) == 1
    assert actions[0].kind == "http"
    assert actions[0].target == "https://x.com/u?token=abc"


def test_parse_list_unsubscribe_empty_returns_empty():
    assert parse_list_unsubscribe(None) == []
    assert parse_list_unsubscribe("") == []
