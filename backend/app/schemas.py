from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .options import MAX_SPEED, MAX_STEPS, MIN_SPEED, MIN_STEPS, build_instruct


class DesignOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gender: Optional[str] = None
    age: Optional[str] = None
    pitch: Optional[str] = None
    style: Optional[str] = None
    accent: Optional[str] = None


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(..., max_length=20000)  # hard cap; the configured limit is enforced in the endpoint
    mode: Literal["auto", "design"] = "auto"
    design: Optional[DesignOptions] = None
    speed: float = Field(1.0, ge=MIN_SPEED, le=MAX_SPEED)
    num_step: int = Field(32, ge=MIN_STEPS, le=MAX_STEPS)

    @model_validator(mode="after")
    def _check_design(self):
        if self.mode == "design" and self.design is not None:
            build_instruct(self.design.model_dump())  # raises ValueError -> HTTP 422
        return self

    def instruct(self) -> Optional[str]:
        if self.mode != "design" or self.design is None:
            return None
        return build_instruct(self.design.model_dump())
