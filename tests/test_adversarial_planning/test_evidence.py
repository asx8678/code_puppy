"""Test evidence tracking system."""

import pytest

from code_puppy.plugins.adversarial_planning.evidence import (
    EvidenceTracker,
    EvidenceValidationError,
)
from code_puppy.plugins.adversarial_planning.models import (
    EvidenceSource,
    EvidenceClass,
    Evidence,
)


class TestEvidenceTracker:
    """Test EvidenceTracker class."""

    @pytest.fixture
    def tracker(self):
        """Create fresh evidence tracker."""
        return EvidenceTracker()

    def test_add_verified(self, tracker):
        """Test adding verified evidence."""
        source = EvidenceSource(kind="file", locator="test.py:10")
        ev_id = tracker.add_verified(
            claim="File exists",
            source=source,
            confidence=95,
        )

        assert ev_id == "EV1"
        evidence = tracker.get(ev_id)
        assert evidence.evidence_class == EvidenceClass.VERIFIED
        assert evidence.confidence == 95

    def test_add_verified_default_confidence(self, tracker):
        """Test verified evidence uses default confidence of 90."""
        source = EvidenceSource(kind="file", locator="test.py:10")
        ev_id = tracker.add_verified(
            claim="File exists",
            source=source,
        )
        evidence = tracker.get(ev_id)
        assert evidence.confidence == 90

    def test_add_verified_confidence_validation(self, tracker):
        """Test verified evidence enforces 90-100 confidence range."""
        source = EvidenceSource(kind="file", locator="test.py:10")
        # Too low
        with pytest.raises(ValueError, match="Verified evidence confidence must be 90-100"):
            tracker.add_verified(claim="Test", source=source, confidence=80)
        # Too high
        with pytest.raises(ValueError, match="Verified evidence confidence must be 90-100"):
            tracker.add_verified(claim="Test", source=source, confidence=105)

    def test_add_inference(self, tracker):
        """Test adding inference evidence."""
        # First add verified evidence to base on
        source = EvidenceSource(kind="file", locator="test.py")
        ev1 = tracker.add_verified("Verified claim", source)

        ev_id = tracker.add_inference(
            claim="Inference claim",
            source=source,
            based_on=[ev1],
            confidence=75,
        )

        evidence = tracker.get(ev_id)
        assert evidence.evidence_class == EvidenceClass.INFERENCE
        assert ev1 in evidence.claim  # Based on should be in claim

    def test_add_inference_requires_base_evidence(self, tracker):
        """Test inference requires at least one base evidence."""
        source = EvidenceSource(kind="file", locator="test.py")
        with pytest.raises(ValueError, match="Inferences must be based_on"):
            tracker.add_inference(
                claim="Inference without base",
                source=source,
                based_on=[],  # Empty - should fail
            )

    def test_add_inference_requires_existing_evidence(self, tracker):
        """Test inference requires existing evidence IDs."""
        source = EvidenceSource(kind="file", locator="test.py")
        with pytest.raises(ValueError, match="Referenced evidence EV999 not found"):
            tracker.add_inference(
                claim="Inference",
                source=source,
                based_on=["EV999"],  # Non-existent
            )

    def test_add_inference_confidence_validation(self, tracker):
        """Test inference enforces 70-89 confidence range."""
        source = EvidenceSource(kind="file", locator="test.py")
        ev1 = tracker.add_verified("Base", source)

        # Too low
        with pytest.raises(ValueError, match="Inference confidence must be 70-89"):
            tracker.add_inference("Test", source, [ev1], confidence=60)
        # Too high
        with pytest.raises(ValueError, match="Inference confidence must be 70-89"):
            tracker.add_inference("Test", source, [ev1], confidence=95)

    def test_add_assumption(self, tracker):
        """Test adding assumption evidence."""
        ev_id = tracker.add_assumption(
            claim="Assumption claim",
            confidence=50,
        )

        evidence = tracker.get(ev_id)
        assert evidence.evidence_class == EvidenceClass.ASSUMPTION
        assert evidence.confidence == 50

    def test_add_assumption_default_confidence(self, tracker):
        """Test assumption uses default confidence of 50."""
        ev_id = tracker.add_assumption(claim="Test assumption")
        evidence = tracker.get(ev_id)
        assert evidence.confidence == 50

    def test_add_assumption_confidence_validation(self, tracker):
        """Test assumption enforces 50-69 confidence range."""
        # Too low
        with pytest.raises(ValueError, match="Assumption confidence must be 50-69"):
            tracker.add_assumption(claim="Test", confidence=40)
        # Too high
        with pytest.raises(ValueError, match="Assumption confidence must be 50-69"):
            tracker.add_assumption(claim="Test", confidence=80)

    def test_add_unknown(self, tracker):
        """Test adding unknown evidence."""
        ev_id = tracker.add_unknown(claim="No idea about X")

        evidence = tracker.get(ev_id)
        assert evidence.evidence_class == EvidenceClass.UNKNOWN
        assert evidence.confidence == 0
        assert "unknown:gap" in evidence.source.locator

    def test_sequential_ids(self, tracker):
        """Test evidence IDs are sequential."""
        source = EvidenceSource(kind="file", locator="test.py")

        id1 = tracker.add_verified("Claim 1", source)
        id2 = tracker.add_inference("Claim 2", source, [id1])
        id3 = tracker.add_assumption("Claim 3")
        id4 = tracker.add_unknown("Claim 4")

        assert id1 == "EV1"
        assert id2 == "EV2"
        assert id3 == "EV3"
        assert id4 == "EV4"

    def test_get_nonexistent(self, tracker):
        """Test getting nonexistent evidence returns None."""
        assert tracker.get("EV999") is None

    def test_to_list(self, tracker):
        """Test exporting all evidence as list."""
        source = EvidenceSource(kind="file", locator="test.py")
        tracker.add_verified("Claim 1", source)
        tracker.add_verified("Claim 2", source)

        evidence_list = tracker.to_list()
        assert len(evidence_list) == 2
        assert all(isinstance(e, Evidence) for e in evidence_list)

    def test_summary(self, tracker):
        """Test evidence summary by class."""
        source = EvidenceSource(kind="file", locator="test.py")
        ev1 = tracker.add_verified("V1", source)
        ev2 = tracker.add_verified("V2", source)
        ev3 = tracker.add_inference("I1", source, [ev1])
        ev4 = tracker.add_assumption("A1")
        ev5 = tracker.add_unknown("U1")

        summary = tracker.summary()
        assert summary["by_class"]["verified"] == 2
        assert summary["by_class"]["inference"] == 1
        assert summary["by_class"]["assumption"] == 1
        assert summary["by_class"]["unknown"] == 1
        assert summary["total"] == 5
        assert "average_confidence" in summary

    def test_get_used_by_empty(self, tracker):
        """Test get_used_by returns empty list for unused evidence."""
        source = EvidenceSource(kind="file", locator="test.py")
        ev1 = tracker.add_verified("Test", source)
        assert tracker.get_used_by(ev1) == []

    def test_get_used_by_returns_copy(self, tracker):
        """Test get_used_by returns a copy, not the original list."""
        source = EvidenceSource(kind="file", locator="test.py")
        ev1 = tracker.add_verified("Test", source)
        used_by = tracker.get_used_by(ev1)
        used_by.append("action1")  # Modifying returned list
        # Original should be unchanged
        assert tracker.get_used_by(ev1) == []

    def test_filter_by_class(self, tracker):
        """Test filtering evidence by class."""
        source = EvidenceSource(kind="file", locator="test.py")
        tracker.add_verified("V1", source)
        tracker.add_verified("V2", source)
        tracker.add_inference("I1", source, ["EV1"])
        tracker.add_assumption("A1")
        tracker.add_unknown("U1")

        verified = tracker.filter_by_class(EvidenceClass.VERIFIED)
        assert len(verified) == 2

        inferences = tracker.filter_by_class(EvidenceClass.INFERENCE)
        assert len(inferences) == 1

    def test_find_by_claim(self, tracker):
        """Test finding evidence by claim pattern."""
        source = EvidenceSource(kind="file", locator="test.py")
        tracker.add_verified("Database connection uses pooling", source)
        tracker.add_verified("API rate limiting is configured", source)
        tracker.add_assumption("OAuth credentials available")

        results = tracker.find_by_claim("connection")
        assert len(results) == 1
        assert "connection" in results[0].claim.lower()

        results = tracker.find_by_claim("OAuth")
        assert len(results) == 1

    def test_find_by_claim_case_insensitive(self, tracker):
        """Test finding evidence is case insensitive."""
        source = EvidenceSource(kind="file", locator="test.py")
        tracker.add_verified("DATABASE configured", source)

        results_lower = tracker.find_by_claim("database")
        results_upper = tracker.find_by_claim("DATABASE")
        results_mixed = tracker.find_by_claim("Database")

        assert len(results_lower) == 1
        assert len(results_upper) == 1
        assert len(results_mixed) == 1


class TestEvidenceValidation:
    """Test evidence validation for actions."""

    @pytest.fixture
    def tracker_with_evidence(self):
        """Create tracker with sample evidence."""
        tracker = EvidenceTracker()
        source = EvidenceSource(kind="file", locator="test.py")

        ev1 = tracker.add_verified("Verified claim", source)  # EV1
        ev2 = tracker.add_inference("Inference claim", source, [ev1])  # EV2
        ev3 = tracker.add_assumption("Assumption claim")  # EV3
        ev4 = tracker.add_unknown("Unknown claim")  # EV4

        return tracker, [ev1, ev2, ev3, ev4]

    def test_verified_supports_irreversible(self, tracker_with_evidence):
        """Test verified evidence supports irreversible actions."""
        tracker, (ev1, _, _, _) = tracker_with_evidence
        valid, issues = tracker.validate_for_action(
            [ev1], action_type="irreversible_work"
        )
        assert valid is True
        assert len(issues) == 0

    def test_verified_supports_reversible(self, tracker_with_evidence):
        """Test verified evidence supports reversible actions."""
        tracker, (ev1, _, _, _) = tracker_with_evidence
        valid, issues = tracker.validate_for_action(
            [ev1], action_type="reversible_probe"
        )
        assert valid is True
        assert len(issues) == 0

    def test_inference_supports_reversible_only(self, tracker_with_evidence):
        """Test inference evidence supports only reversible actions."""
        tracker, (_, ev2, _, _) = tracker_with_evidence
        # Reversible is OK
        valid, issues = tracker.validate_for_action(
            [ev2], action_type="reversible_probe"
        )
        assert valid is True
        assert len(issues) == 0

        # Irreversible is NOT OK
        valid, issues = tracker.validate_for_action(
            [ev2], action_type="irreversible_work"
        )
        assert valid is False
        assert len(issues) > 0
        assert "inference" in issues[0].lower()

    def test_assumption_requires_verification_task(self, tracker_with_evidence):
        """Test assumption evidence is valid for verification task action."""
        tracker, (_, _, ev3, _) = tracker_with_evidence

        # Normal actions should fail for assumption evidence
        valid, issues = tracker.validate_for_action(
            [ev3], action_type="reversible_probe"
        )
        assert valid is False
        assert "assumption" in issues[0].lower()

        # Verification task should accept assumption evidence
        valid, issues = tracker.validate_for_action(
            [ev3], action_type="verification_task"
        )
        assert valid is True  # ASSUMPTION is valid for verification_task
        assert len(issues) == 0

    def test_unknown_must_be_blocker(self, tracker_with_evidence):
        """Test unknown evidence is valid for blocker action."""
        tracker, (_, _, _, ev4) = tracker_with_evidence

        # Normal actions should fail for unknown evidence
        valid, issues = tracker.validate_for_action(
            [ev4], action_type="reversible_probe"
        )
        assert valid is False
        assert "unknown" in issues[0].lower()

        # Blocker action should accept unknown evidence
        valid, issues = tracker.validate_for_action(
            [ev4], action_type="blocker"
        )
        assert valid is True  # UNKNOWN is valid for blocker action
        assert len(issues) == 0

    def test_validate_with_multiple_evidence(self, tracker_with_evidence):
        """Test validation with multiple evidence items."""
        tracker, (ev1, ev2, _, _) = tracker_with_evidence

        # Both verified and inference together
        valid, issues = tracker.validate_for_action(
            [ev1, ev2], action_type="reversible_probe"
        )
        assert valid is True

        # For irreversible, inference blocks it
        valid, issues = tracker.validate_for_action(
            [ev1, ev2], action_type="irreversible_work"
        )
        assert valid is False
        assert any("inference" in issue.lower() for issue in issues)

    def test_validate_nonexistent_evidence(self, tracker_with_evidence):
        """Test validation with nonexistent evidence ID."""
        tracker, _ = tracker_with_evidence

        valid, issues = tracker.validate_for_action(
            ["EV999"], action_type="reversible_probe"
        )
        assert valid is False
        assert any("not found" in issue.lower() for issue in issues)

    def test_validate_tracks_usage(self, tracker_with_evidence):
        """Test validation tracks which actions use evidence."""
        tracker, (ev1, _, _, _) = tracker_with_evidence

        # Validate with action_id
        tracker.validate_for_action(
            [ev1], action_type="irreversible_work", action_id="action_1"
        )

        # Check tracking
        used_by = tracker.get_used_by(ev1)
        assert "action_1" in used_by
