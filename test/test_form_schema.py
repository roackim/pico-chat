import pytest

from pico_chat.ui.tui.components.form import (
    CheckboxListField, RadioListField, TextAreaField, TextField, ToggleField,
)
from pico_chat.ui.tui.components.form_schema import FormFieldSpec, build_field, build_fields


def test_build_fields_preserves_schema_order_and_types():
    fields = build_fields([
        FormFieldSpec("Name", value="server", required=True),
        FormFieldSpec("Enabled", kind="toggle", value=True),
        FormFieldSpec("Notes", kind="textarea", min_lines=5),
        FormFieldSpec("Tags", kind="checkbox", options=["a", "b"], value=[1]),
        FormFieldSpec("Type", kind="radio", options=["one", "two"], value=1),
    ])

    assert [field.label for field in fields] == ["Name", "Enabled", "Notes", "Tags", "Type"]
    assert isinstance(fields[0], TextField)
    assert isinstance(fields[1], ToggleField)
    assert isinstance(fields[2], TextAreaField)
    assert isinstance(fields[3], CheckboxListField)
    assert isinstance(fields[4], RadioListField)
    assert fields[3].get_value() == [1]
    assert fields[4].get_value() == 1


def test_build_field_attaches_custom_validator_to_model():
    field = build_field(FormFieldSpec(
        "Port", value="bad", validator=lambda value: "Not a number"
        if not value.isdigit() else None,
    ))

    assert not field.validate()
    assert field.model.error == "Not a number"


def test_build_field_rejects_unknown_kind():
    with pytest.raises(ValueError, match="Unknown form field kind: slider"):
        build_field(FormFieldSpec("Volume", kind="slider"))