from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


NO_ANSWER_RESPONSE = "I don't have any information on this topic."


class StructuredChatbotResponse(BaseModel):
    """Validated final answer contract for the chatbot brain model."""

    message_type: Literal["PURE_GREETING", "NON_GREETING"] = Field(
        description="Classification of the latest user message."
    )
    answer_html: str = Field(
        description="User-facing answer content. Use brief HTML like <p> and <ul><li> when helpful."
    )
    citation_ids: list[int] = Field(
        default_factory=list,
        description="Unique source numbers used in the answer, matching Source N in retrieved grounding.",
    )

    @field_validator("answer_html")
    @classmethod
    def _validate_answer_html(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("answer_html must not be empty")
        return cleaned

    @field_validator("citation_ids")
    @classmethod
    def _validate_citation_ids(cls, value: list[int]) -> list[int]:
        seen: set[int] = set()
        unique_ids: list[int] = []
        for item in value or []:
            if item <= 0:
                raise ValueError("citation_ids must contain only positive integers")
            if item not in seen:
                seen.add(item)
                unique_ids.append(item)
        return unique_ids

    @model_validator(mode="after")
    def _validate_grounding_contract(self) -> "StructuredChatbotResponse":
        if self.message_type == "PURE_GREETING":
            if self.citation_ids:
                raise ValueError("PURE_GREETING responses must not include citation_ids")
            return self

        if self.answer_html == NO_ANSWER_RESPONSE:
            if self.citation_ids:
                raise ValueError("No-answer responses must not include citation_ids")
            return self

        if not self.citation_ids:
            raise ValueError("NON_GREETING factual responses must include at least one citation_id")

        return self
