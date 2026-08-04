from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, List, Optional

from pico_chat.ui.tui.components.field_models import FieldModel
from pico_chat.ui.tui.components.form import (
    CheckboxListField,
    FormField,
    RadioListField,
    TextAreaField,
    TextField,
    ToggleField,
)


@dataclass
class FormFieldSpec:
    """Declarative description of one form field."""

    label: str
    kind: str = "text"
    value: Any = ""
    required: bool = False
    placeholder: str = ""
    options: List[str] = field(default_factory=list)
    min_lines: int = 3
    validator: Optional[Callable[[Any], Optional[str]]] = None
    async_validator: Optional[Callable[[Any], Awaitable[Optional[str]]]] = None


def build_field(spec: FormFieldSpec) -> FormField:
    """Build a regular form field from a declarative specification."""
    common = {"required": spec.required}
    if spec.validator is not None:
        common["model"] = FieldModel(
            spec.value, required=spec.required, validator=spec.validator,
            async_validator=spec.async_validator)
    elif spec.async_validator is not None:
        common["model"] = FieldModel(
            spec.value, required=spec.required,
            async_validator=spec.async_validator)

    if spec.kind == "text":
        return TextField(spec.label, value=spec.value, placeholder=spec.placeholder,
                         **common)
    if spec.kind == "textarea":
        return TextAreaField(spec.label, value=spec.value,
                             placeholder=spec.placeholder, min_lines=spec.min_lines,
                             **common)
    if spec.kind == "toggle":
        return ToggleField(spec.label, value=bool(spec.value), **common)
    if spec.kind == "checkbox":
        return CheckboxListField(spec.label, options=spec.options,
                                 value=spec.value, **common)
    if spec.kind == "radio":
        return RadioListField(spec.label, options=spec.options,
                              value=spec.value, **common)
    raise ValueError(f"Unknown form field kind: {spec.kind}")


def build_fields(specs: List[FormFieldSpec]) -> List[FormField]:
    """Build fields in schema order."""
    return [build_field(spec) for spec in specs]
