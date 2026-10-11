from pydantic import BaseModel, ConfigDict, Field, model_validator


class Chunk(BaseModel):
    """A contiguous range of lines from a ``SourceDocument``.

    Invariant: ``content`` is exactly lines ``start_line``..``end_line`` (1-based,
    inclusive) of the document, line endings included. Citations rely on it.
    """

    model_config = ConfigDict(frozen=True)

    path: str
    language: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    content: str
    # Heading breadcrumb for documentation ("Install > Windows"), if any.
    section: str | None = None

    @model_validator(mode="after")
    def _check_line_range(self) -> "Chunk":
        if self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")
        return self
