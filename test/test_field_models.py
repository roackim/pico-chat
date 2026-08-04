import asyncio
import pytest

from pico_chat.ui.tui.components.field_models import FieldModel


def test_field_model_tracks_dirty_and_reset():
    model = FieldModel("before")

    model.set_value("after")
    assert model.value == "after"
    assert model.dirty

    model.reset()
    assert model.value == "before"
    assert not model.dirty
    assert model.error is None


def test_required_model_rejects_blank_strings():
    model = FieldModel("", required=True)

    assert not model.validate()
    assert model.error == "This field is required"

    model.set_value("ready")
    assert model.validate()
    assert model.error is None


def test_custom_validator_sets_and_clears_error():
    model = FieldModel(3, validator=lambda value: "Too small" if value < 5 else None)

    assert not model.validate()
    assert model.error == "Too small"

    model.set_value(5)
    assert model.validate()
    assert model.error is None


def test_async_validation_is_an_explicit_extension_point():
    async def validate_remote(value):
        return "Already used" if value == "taken" else None

    model = FieldModel("taken", async_validator=validate_remote)

    assert model.validate()
    assert asyncio.run(model.validate_async()) is False
    assert model.error == "Already used"
