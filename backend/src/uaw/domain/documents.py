from pydantic import BaseModel, ConfigDict


class SourceDocument(BaseModel):
    """A text file imported from a data source, before chunking.

    ``path`` is a normalized POSIX path relative to the source root. Connectors
    guarantee it never contains ``..``, empty segments or a leading ``/``.
    """

    model_config = ConfigDict(frozen=True)

    path: str
    language: str
    content: str
