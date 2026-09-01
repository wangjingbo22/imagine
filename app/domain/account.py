from __future__ import annotations

from typing import Annotated
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    UUID4,
    alias_generators,
    field_validator,
)


class AccountModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=alias_generators.to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


AccountInterest = Annotated[str, Field(min_length=1, max_length=80)]
AccountDisplayName = Annotated[str, Field(min_length=1, max_length=80)]
AccountHomeCity = Annotated[str, Field(min_length=1, max_length=80)]


class RegisterRequest(AccountModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=12, max_length=128)]
    display_name: AccountDisplayName


class LoginRequest(AccountModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=12, max_length=128)]


class ProfileUpdateRequest(AccountModel):
    display_name: AccountDisplayName
    home_city: AccountHomeCity | None = None
    interests: list[AccountInterest] = Field(default_factory=list, max_length=8)


class CurrentUser(AccountModel):
    user_id: UUID4
    email: EmailStr
    display_name: AccountDisplayName
    home_city: AccountHomeCity | None = None
    interests: list[AccountInterest] = Field(default_factory=list, max_length=8)


class LogoutResult(AccountModel):
    logged_out: bool = True


class ModelSettingsUpdateRequest(AccountModel):
    model: Annotated[
        str,
        Field(
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9._:/@-]+$",
        ),
    ]
    api_key: Annotated[SecretStr, Field(min_length=1, max_length=512)]
    base_url: Annotated[str, Field(min_length=12, max_length=300)]

    @field_validator("api_key")
    @classmethod
    def reject_api_key_control_characters(cls, value: SecretStr) -> SecretStr:
        api_key = value.get_secret_value()
        if any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in api_key):
            raise ValueError("API Key 不能包含控制字符或换行")
        return value


class ModelSettingsView(AccountModel):
    configured: bool
    model: str | None = None
    base_url: str | None = None


def normalized_email(email: str | EmailStr) -> str:
    return str(email).strip().casefold()
