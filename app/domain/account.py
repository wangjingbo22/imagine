from __future__ import annotations

from typing import Annotated
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    UUID4,
    alias_generators,
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


def normalized_email(email: str | EmailStr) -> str:
    return str(email).strip().casefold()
