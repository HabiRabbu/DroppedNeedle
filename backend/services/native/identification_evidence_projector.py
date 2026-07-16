"""Shared persisted-evidence projection for all identification consumers."""

from __future__ import annotations

from models.identification import CandidateEvidence, EvidenceProjection


class IdentificationEvidenceProjector:
    def project(self, evidence: CandidateEvidence) -> EvidenceProjection:
        return EvidenceProjection(
            supported_track_ids=[
                track.local_track_id
                for track in evidence.track_evidence
                if track.classification == "supported"
            ],
            unknown_track_ids=[
                track.local_track_id
                for track in evidence.track_evidence
                if track.classification == "unknown"
            ],
            contradictory_track_ids=[
                track.local_track_id
                for track in evidence.track_evidence
                if track.classification == "contradictory"
            ],
            reason_code=evidence.reason_code,
        )

    def for_review(self, evidence: CandidateEvidence) -> EvidenceProjection:
        return self.project(evidence)

    def for_repair(self, evidence: CandidateEvidence) -> EvidenceProjection:
        return self.project(evidence)

    def for_candidate_preview(self, evidence: CandidateEvidence) -> EvidenceProjection:
        return self.project(evidence)

    def for_reidentification(self, evidence: CandidateEvidence) -> EvidenceProjection:
        return self.project(evidence)
