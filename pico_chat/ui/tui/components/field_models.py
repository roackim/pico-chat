from typing import Awaitable, Callable, Generic, Optional, TypeVar


T = TypeVar("T")
Validator = Callable[[T], Optional[str]]
AsyncValidator = Callable[[T], Awaitable[Optional[str]]]


class FieldModel(Generic[T]):
    """Value and validation state independent from a form widget."""

    def __init__(self, value: T, *, required: bool = False,
                 validator: Optional[Validator[T]] = None,
                 async_validator: Optional[AsyncValidator[T]] = None):
        self.initial_value = value
        self.value = value
        self.required = required
        self.validator = validator
        self.async_validator = async_validator
        self.error: Optional[str] = None

    @property
    def dirty(self) -> bool:
        return self.value != self.initial_value

    def set_value(self, value: T):
        self.value = value
        self.error = None

    def reset(self):
        self.value = self.initial_value
        self.error = None

    def validate(self) -> bool:
        if self.required and (self.value is None or (isinstance(self.value, str) and not self.value.strip())):
            self.error = "This field is required"
        elif self.validator is not None:
            self.error = self.validator(self.value)
        else:
            self.error = None
        return self.error is None

    async def validate_async(self) -> bool:
        """Run synchronous validation, then optional asynchronous validation."""
        if not self.validate():
            return False
        if self.async_validator is not None:
            self.error = await self.async_validator(self.value)
        return self.error is None


class TextFieldModel(FieldModel[str]):
    def __init__(self, value: str = "", **kwargs):
        super().__init__(value, **kwargs)


class BoolFieldModel(FieldModel[bool]):
    def __init__(self, value: bool = False, **kwargs):
        super().__init__(bool(value), **kwargs)


class ChoiceFieldModel(FieldModel[Optional[int]]):
    def __init__(self, value: Optional[int] = None, **kwargs):
        super().__init__(value, **kwargs)
