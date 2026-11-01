"""Evidence persistence and retrieval package for Bharmafills."""

from app.services.evidence.exceptions import (
    DuplicateExtractionRunError,
    EvidencePersistenceError,
    EvidenceTransactionError,
    ExtractionRunNotFoundError,
    InvalidEvidencePayloadError,
    SourceMismatchError,
)
from app.services.evidence.persistence_service import (
    EvidencePersistenceService,
    get_evidence_persistence_service,
)
from app.services.evidence.schemas import (
    BatchPersistenceResponse,
    ExtractionRunListResponse,
    ExtractionRunResponse,
    PersistEvidenceRequest,
    PersistedClaimResponse,
    PersistedEvidenceRunResponse,
    PersistedFactResponse,
    ProjectEvidenceResponse,
)

__all__ = [
    "EvidencePersistenceService",
    "get_evidence_persistence_service",
    "EvidencePersistenceError",
    "ExtractionRunNotFoundError",
    "SourceMismatchError",
    "DuplicateExtractionRunError",
    "InvalidEvidencePayloadError",
    "EvidenceTransactionError",
    "PersistedFactResponse",
    "PersistedClaimResponse",
    "ExtractionRunResponse",
    "PersistedEvidenceRunResponse",
    "BatchPersistenceResponse",
    "ProjectEvidenceResponse",
    "ExtractionRunListResponse",
    "PersistEvidenceRequest",
]

