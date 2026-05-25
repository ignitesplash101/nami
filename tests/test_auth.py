from __future__ import annotations

from app.api.security import (
    can_use_custom_portfolio,
    can_use_free_text_scenario,
    can_use_narrative_decomposition,
    create_admin_token,
    verify_admin_token,
    verify_passcode,
)


def test_visitor_access_is_limited():
    assert not can_use_free_text_scenario("visitor")
    assert not can_use_custom_portfolio("visitor")
    assert not can_use_narrative_decomposition("visitor")


def test_admin_access_is_unrestricted():
    assert can_use_free_text_scenario("admin")
    assert can_use_custom_portfolio("admin")
    assert can_use_narrative_decomposition("admin")


def test_verify_passcode_accepts_correct_value():
    assert verify_passcode("correct horse battery staple", "correct horse battery staple")


def test_verify_passcode_rejects_wrong_or_empty_values():
    assert not verify_passcode("wrong", "correct horse battery staple")
    assert not verify_passcode("", "correct horse battery staple")
    assert not verify_passcode("correct horse battery staple", "")


def test_admin_token_is_signed_and_secret_bound():
    token = create_admin_token("secret-a")
    assert token is not None
    assert verify_admin_token(token, "secret-a")
    assert not verify_admin_token(token, "secret-b")
