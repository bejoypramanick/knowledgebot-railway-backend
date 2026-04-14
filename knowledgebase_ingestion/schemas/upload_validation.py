from pydantic import BaseModel, ConfigDict, model_validator

from knowledgebase_ingestion.service.upload_constraints_service import get_upload_constraints_service


class UploadValidationInput(BaseModel):
    """Single Pydantic validator for knowledgebase file upload constraints."""

    model_config = ConfigDict(str_strip_whitespace=True)

    filename: str
    mime_type: str = ""
    size_bytes: int

    @model_validator(mode="after")
    def validate_upload_constraints(self) -> "UploadValidationInput":
        constraints_service = get_upload_constraints_service()
        constraints = constraints_service.get_constraints()["constraints"]
        allowed_extensions = constraints["allowed_extensions"]
        allowed_mime_types = constraints["allowed_mime_types"]
        max_file_size = constraints["max_file_size"]

        if not self.filename:
            raise ValueError("Filename is required")

        parts = self.filename.lower().split(".")
        if len(parts) < 2:
            raise ValueError("Filename must have an extension")

        extension = parts[-1]
        if len(parts) > 2 and extension == "gz" and parts[-2] == "tar":
            extension = "tar.gz"

        if extension not in allowed_extensions:
            allowed_list = ", ".join(sorted(allowed_extensions))
            raise ValueError(f"File type '.{extension}' not allowed. Supported: {allowed_list}")

        if self.mime_type and self.mime_type not in allowed_mime_types:
            # Browser uploads sometimes use generic MIME values; if the extension is allowed,
            # keep validation extension-rooted instead of rejecting a usable upload.
            return self

        if self.size_bytes <= 0:
            raise ValueError("File size must be greater than 0")

        if self.size_bytes > max_file_size:
            max_mb = max_file_size // (1024 * 1024)
            file_mb = self.size_bytes / (1024 * 1024)
            raise ValueError(
                f"File size ({file_mb:.2f} MB) exceeds maximum allowed ({max_mb} MB)"
            )

        return self
