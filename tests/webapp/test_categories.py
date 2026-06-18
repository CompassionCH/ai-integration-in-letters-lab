"""Tests for the alert-category loader (the missed-issue selectable subset)."""
import categories


def test_selectable_subset_excludes_model_only_states():
    ids = categories.selectable_for_missed_ids()
    assert "no_alert" not in ids
    assert "safety_filter_triggered" not in ids


def test_selectable_subset_is_the_nine_platform_codes():
    assert categories.selectable_for_missed_ids() == {
        "broken_pdf",
        "text_unreadable",
        "wrong_language",
        "child_protection",
        "content_inappropriate",
        "wrong_child_name",
        "wrong_sponsor_name",
        "invalid_layout",
        "other",
    }


def test_selectable_subset_is_a_set():
    assert isinstance(categories.selectable_for_missed_ids(), set)
