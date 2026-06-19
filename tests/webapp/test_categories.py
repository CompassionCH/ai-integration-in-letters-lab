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


def test_selectable_for_missed_carries_labels_in_order():
    entries = categories.selectable_for_missed()
    assert [e["id"] for e in entries] == [
        "broken_pdf",
        "text_unreadable",
        "wrong_language",
        "child_protection",
        "content_inappropriate",
        "wrong_child_name",
        "wrong_sponsor_name",
        "invalid_layout",
        "other",
    ]
    assert all(e["label_en"] for e in entries)  # every option has a non-empty label


def test_label_for_returns_label_or_id_fallback():
    assert categories.label_for("wrong_child_name") == "Child name different than expected"
    assert categories.label_for("no_alert") == "No issue"  # resolves non-selectable too
    assert categories.label_for("does_not_exist") == "does_not_exist"  # fallback to the id
