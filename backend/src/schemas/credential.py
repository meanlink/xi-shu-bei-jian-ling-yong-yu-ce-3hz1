from pydantic import BaseModel, Field


class VerifyInput(BaseModel):
    from_seq: int = Field(ge=1)
    to_seq: int = Field(ge=1)
