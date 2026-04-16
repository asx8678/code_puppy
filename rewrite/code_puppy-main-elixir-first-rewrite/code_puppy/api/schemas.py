"""API schemas for Code Puppy REST API."""

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response wrapper."""

    items: list[T]
    total: int = Field(description="Total number of items available")
    offset: int = Field(description="Current offset (0-indexed)")
    limit: int = Field(description="Number of items per page")
    has_more: bool = Field(description="Whether more items exist after this page")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [],
                "total": 100,
                "offset": 0,
                "limit": 50,
                "has_more": True,
            }
        }
    )
