"""Evidence tracking system for adversarial planning.

The evidence system enforces a strict confidence hierarchy:
- VERIFIED (90-100): Can support irreversible work
- INFERENCE (70-89): Can support reversible probes only
- ASSUMPTION (50-69): Must become task/gate/blocker
- UNKNOWN (0-49): Must be blocker/gate/out-of-scope

Evidence IDs are auto-generated (EV1, EV2, ...) for cross-referencing.
"""

import logging

from .models import (
    Evidence,
    EvidenceClass,
    EvidenceSource,
)

logger = logging.getLogger(__name__)


class EvidenceValidationError(Exception):
    """Raised when evidence validation fails for an action."""
    pass


class EvidenceTracker:
    """Track and validate evidence throughout adversarial planning.
    
    Enforces the evidence confidence hierarchy and validates whether
    evidence supports various action types per the allowed use rules:
    
    - VERIFIED: Can support irreversible work
    - INFERENCE: Can support reversible probes only
    - ASSUMPTION: Must become verification task/gate/blocker
    - UNKNOWN: Must be blocker/gate/out-of-scope
    
    Example:
        >>> tracker = EvidenceTracker()
        >>> source = EvidenceSource(kind="file", locator="src/app.py:10-20")
        >>> ev_id = tracker.add_verified("Database connection uses pooling", source)
        >>> tracker.add_inference("Pool size is 10", source, based_on=[ev_id], confidence=75)
    """
    
    # Confidence thresholds per evidence class
    CONFIDENCE_VERIFIED = (90, 100)
    CONFIDENCE_INFERENCE = (70, 89)
    CONFIDENCE_ASSUMPTION = (50, 69)
    CONFIDENCE_UNKNOWN = (0, 49)
    
    def __init__(self):
        self._evidence: dict[str, Evidence] = {}
        self._next_id = 1
        self._used_by: dict[str, list[str]] = {}  # evidence_id -> list of action_ids
    
    def _generate_id(self) -> str:
        """Generate next evidence ID (EV1, EV2, ...)."""
        ev_id = f"EV{self._next_id}"
        self._next_id += 1
        return ev_id
    
    def _add_evidence(self, evidence: Evidence) -> str:
        """Internal method to add evidence to the tracker."""
        self._evidence[evidence.id] = evidence
        self._used_by[evidence.id] = []
        logger.debug(f"Added evidence {evidence.id}: {evidence.claim[:50]}...")
        return evidence.id
    
    def add_verified(
        self, 
        claim: str, 
        source: EvidenceSource, 
        confidence: int = 90
    ) -> str:
        """Add verified evidence (directly confirmed).
        
        Verified evidence comes from direct observation of the codebase:
        - Reading a file and seeing the actual code
        - Running tests that pass/fail
        - Examining CI configuration
        - Reading logs
        
        Args:
            claim: The specific claim being verified
            source: Where this was observed (file, test, etc.)
            confidence: 90-100 (default 90)
            
        Returns:
            The generated evidence ID (e.g., "EV1")
            
        Raises:
            ValueError: If confidence is not in the VERIFIED range
        """
        if not (90 <= confidence <= 100):
            raise ValueError(
                f"Verified evidence confidence must be 90-100, got {confidence}"
            )
        
        ev_id = self._generate_id()
        evidence = Evidence(
            id=ev_id,
            evidence_class=EvidenceClass.VERIFIED,
            claim=claim,
            source=source,
            confidence=confidence,
        )
        return self._add_evidence(evidence)
    
    def add_inference(
        self, 
        claim: str, 
        source: EvidenceSource,
        based_on: list[str],
        confidence: int = 70
    ) -> str:
        """Add inference (reasonable conclusion from verified facts).
        
        Inferences require supporting evidence. Chain them to base facts.
        Inferences can only support reversible work.
        
        Args:
            claim: The inferred claim
            source: Where the inference was made
            based_on: List of evidence IDs this inference depends on
            confidence: 70-89 (default 70)
            
        Returns:
            The generated evidence ID (e.g., "EV2")
            
        Raises:
            ValueError: If confidence is not in INFERENCE range or based_on is empty
        """
        if not (70 <= confidence <= 89):
            raise ValueError(
                f"Inference confidence must be 70-89, got {confidence}"
            )
        if not based_on:
            raise ValueError("Inferences must be based_on at least one verified evidence")
        
        # Validate that all base evidence exists
        for base_id in based_on:
            if base_id not in self._evidence:
                raise ValueError(f"Referenced evidence {base_id} not found")
        
        ev_id = self._generate_id()
        evidence = Evidence(
            id=ev_id,
            evidence_class=EvidenceClass.INFERENCE,
            claim=f"[Based on {', '.join(based_on)}] {claim}",
            source=source,
            confidence=confidence,
        )
        return self._add_evidence(evidence)
    
    def add_assumption(
        self, 
        claim: str, 
        confidence: int = 50
    ) -> str:
        """Add assumption (not verified, must become task/gate/blocker).
        
        Assumptions are things we're accepting as true without
        verification. They are risks that must be addressed.
        
        Args:
            claim: The assumption being made
            confidence: 50-69 (default 50)
            
        Returns:
            The generated evidence ID (e.g., "EV3")
            
        Raises:
            ValueError: If confidence is not in ASSUMPTION range
        """
        if not (50 <= confidence <= 69):
            raise ValueError(
                f"Assumption confidence must be 50-69, got {confidence}"
            )
        
        ev_id = self._generate_id()
        # Assumptions have no source since they're not verified
        source = EvidenceSource(kind="prompt", locator="assumption:unverified")
        evidence = Evidence(
            id=ev_id,
            evidence_class=EvidenceClass.ASSUMPTION,
            claim=claim,
            source=source,
            confidence=confidence,
        )
        return self._add_evidence(evidence)
    
    def add_unknown(
        self, 
        claim: str
    ) -> str:
        """Add unknown (must become blocker/gate/out-of-scope).
        
        Unknowns are recognized gaps in knowledge. Unlike assumptions,
        we explicitly don't know. These must be addressed.
        
        Args:
            claim: Description of what is unknown
            
        Returns:
            The generated evidence ID (e.g., "EV4")
        """
        ev_id = self._generate_id()
        # Unknowns have no source since they're gaps
        source = EvidenceSource(kind="prompt", locator="unknown:gap")
        evidence = Evidence(
            id=ev_id,
            evidence_class=EvidenceClass.UNKNOWN,
            claim=claim,
            source=source,
            confidence=0,
        )
        return self._add_evidence(evidence)
    
    def get(self, evidence_id: str) -> Evidence | None:
        """Get evidence by ID.
        
        Args:
            evidence_id: The evidence ID (e.g., "EV1")
            
        Returns:
            The Evidence if found, None otherwise
        """
        return self._evidence.get(evidence_id)
    
    def validate_for_action(
        self, 
        evidence_ids: list[str], 
        action_type: str,
        action_id: str | None = None
    ) -> tuple[bool, list[str]]:
        """Validate evidence supports action type per allowed use rules.
        
        Evidence classes have specific allowed uses:
        - VERIFIED (90-100): Can support irreversible work
        - INFERENCE (70-89): Can support reversible probes only
        - ASSUMPTION (50-69): Must become verification task/gate/blocker
        - UNKNOWN (0-49): Must be blocker/gate/out-of-scope
        
        Args:
            evidence_ids: List of evidence IDs supporting the action
            action_type: The type of action ("reversible_probe", 
                        "irreversible_work", "verification_task")
            action_id: Optional identifier for the action (for tracking)
            
        Returns:
            Tuple of (is_valid, list of issues)
            
        Example:
            >>> ok, issues = tracker.validate_for_action(
            ...     ["EV1", "EV2"], 
            ...     "irreversible_work"
            ... )
            >>> if not ok:
            ...     print(f"Validation failed: {issues}")
        """
        issues: list[str] = []
        is_valid = True
        
        for ev_id in evidence_ids:
            evidence = self._evidence.get(ev_id)
            if evidence is None:
                issues.append(f"Evidence {ev_id} not found")
                is_valid = False
                continue
            
            if action_type == "irreversible_work":
                # Only VERIFIED can support irreversible work
                if evidence.evidence_class != EvidenceClass.VERIFIED:
                    issues.append(
                        f"{ev_id} is {evidence.evidence_class.value} "
                        f"(confidence {evidence.confidence}) - "
                        f"only VERIFIED (90-100) can support irreversible work"
                    )
                    is_valid = False
                    
            elif action_type == "reversible_probe":
                # VERIFIED and INFERENCE can support reversible probes
                if evidence.evidence_class not in (
                    EvidenceClass.VERIFIED, 
                    EvidenceClass.INFERENCE
                ):
                    issues.append(
                        f"{ev_id} is {evidence.evidence_class.value} "
                        f"(confidence {evidence.confidence}) - "
                        f"only VERIFIED (90-100) or INFERENCE (70-89) "
                        f"can support reversible probes"
                    )
                    is_valid = False
                    
            elif action_type == "verification_task":
                # ASSUMPTION must become verification task
                if evidence.evidence_class != EvidenceClass.ASSUMPTION:
                    issues.append(
                        f"{ev_id} is {evidence.evidence_class.value} - "
                        f"only ASSUMPTION should become verification tasks"
                    )
                    is_valid = False
                    
            elif action_type == "blocker":
                # UNKNOWN must become blocker/gate
                if evidence.evidence_class != EvidenceClass.UNKNOWN:
                    issues.append(
                        f"{ev_id} is {evidence.evidence_class.value} - "
                        f"only UNKNOWN must become blockers/gates"
                    )
                    is_valid = False
            
            # Track that this evidence is used by an action
            if action_id and is_valid:
                self._used_by[ev_id].append(action_id)
        
        return is_valid, issues
    
    def to_list(self) -> list[Evidence]:
        """Export all evidence as list.
        
        Returns:
            List of all Evidence objects in the tracker
        """
        return list(self._evidence.values())
    
    def summary(self) -> dict[str, int | dict[str, int]]:
        """Summary counts by class and confidence ranges.
        
        Returns:
            Dictionary with:
            - total: Total evidence count
            - by_class: Count per EvidenceClass
            - by_confidence: Count per confidence range
            - average_confidence: Mean confidence score
        """
        by_class: dict[str, int] = {
            "verified": 0,
            "inference": 0,
            "assumption": 0,
            "unknown": 0,
        }
        by_confidence: dict[str, int] = {
            "90-100 (verified)": 0,
            "70-89 (inference)": 0,
            "50-69 (assumption)": 0,
            "0-49 (unknown)": 0,
        }
        
        total_confidence = 0
        
        for ev in self._evidence.values():
            by_class[ev.evidence_class.value] += 1
            total_confidence += ev.confidence
            
            if 90 <= ev.confidence <= 100:
                by_confidence["90-100 (verified)"] += 1
            elif 70 <= ev.confidence <= 89:
                by_confidence["70-89 (inference)"] += 1
            elif 50 <= ev.confidence <= 69:
                by_confidence["50-69 (assumption)"] += 1
            else:
                by_confidence["0-49 (unknown)"] += 1
        
        avg_confidence = (
            total_confidence / len(self._evidence) 
            if self._evidence else 0
        )
        
        return {
            "total": len(self._evidence),
            "by_class": by_class,
            "by_confidence": by_confidence,
            "average_confidence": round(avg_confidence, 1),
        }
    
    def get_used_by(self, evidence_id: str) -> list[str]:
        """Get list of action IDs that use this evidence.
        
        Args:
            evidence_id: The evidence ID to query
            
        Returns:
            List of action IDs that reference this evidence
        """
        return self._used_by.get(evidence_id, []).copy()
    
    def filter_by_class(self, evidence_class: EvidenceClass) -> list[Evidence]:
        """Get all evidence of a specific class.
        
        Args:
            evidence_class: The class to filter by
            
        Returns:
            List of Evidence objects matching the class
        """
        return [
            ev for ev in self._evidence.values()
            if ev.evidence_class == evidence_class
        ]
    
    def find_by_claim(self, pattern: str) -> list[Evidence]:
        """Find evidence where claim contains pattern.
        
        Args:
            pattern: Substring to search for in claims
            
        Returns:
            List of matching Evidence objects
        """
        return [
            ev for ev in self._evidence.values()
            if pattern.lower() in ev.claim.lower()
        ]
