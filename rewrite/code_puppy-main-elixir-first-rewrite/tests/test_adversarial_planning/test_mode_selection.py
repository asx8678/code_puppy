"""Test mode selection logic in detail."""

import pytest

from code_puppy.plugins.adversarial_planning.orchestrator import AdversarialPlanningOrchestrator
from code_puppy.plugins.adversarial_planning.models import (
    AdversarialPlanConfig,
    WorkspaceContext,
    Phase0AOutput,
    Phase0BOutput,
    Evidence,
    EvidenceSource,
    EvidenceClass,
    CriticalUnknown,
)


class TestDeepModeTriggers:
    """Test all deep mode trigger conditions."""

    @pytest.fixture
    def base_config(self):
        return AdversarialPlanConfig(
            mode="auto",
            context=WorkspaceContext(workspace="/test"),
            task="Test task",
        )

    @pytest.fixture
    def base_discovery(self):
        return Phase0AOutput(
            readiness="ready",
            confidence=80,
            workspace_summary="Test",
            problem_signature="Test problem",
            evidence=[],
            files_examined=[],
            existing_patterns_to_reuse=[],
            contradictions=[],
            blast_radius=[],
            critical_unknowns=[],
        )

    @pytest.fixture
    def base_scope(self):
        return Phase0BOutput(
            normalized_problem="Test",
            problem_type="feature",
            verified_facts=[],
            inferences=[],
            hard_constraints=[],
            in_scope=[],
            out_of_scope=[],
            critical_unknowns=[],
            planning_guardrails=[],
            pre_mortem={"scenario": "", "causes": []},
        )

    def test_production_change_triggers_deep(self, base_config, base_discovery):
        """Test production_change in evidence triggers deep mode."""
        base_discovery.evidence.append(
            Evidence(
                id="EV1",
                evidence_class=EvidenceClass.VERIFIED,
                claim="This is a production_change that affects live users",
                source=EvidenceSource(kind="file", locator="deploy.yml"),
                confidence=90,
            )
        )

        orchestrator = AdversarialPlanningOrchestrator(base_config)
        orchestrator.session.phase_0a_output = base_discovery
        orchestrator._select_mode()

        assert orchestrator.session.mode_selected == "deep"

    def test_data_migration_triggers_deep(self, base_config, base_discovery):
        """Test data_migration triggers deep mode."""
        base_discovery.evidence.append(
            Evidence(
                id="EV1",
                evidence_class=EvidenceClass.VERIFIED,
                claim="Requires data_migration of user table",
                source=EvidenceSource(kind="file", locator="migrate.py"),
                confidence=90,
            )
        )

        orchestrator = AdversarialPlanningOrchestrator(base_config)
        orchestrator.session.phase_0a_output = base_discovery
        orchestrator._select_mode()

        assert orchestrator.session.mode_selected == "deep"

    def test_security_risk_triggers_deep(self, base_config, base_discovery):
        """Test security_risk triggers deep mode."""
        base_discovery.evidence.append(
            Evidence(
                id="EV1",
                evidence_class=EvidenceClass.VERIFIED,
                claim="Potential security_risk in auth module",
                source=EvidenceSource(kind="file", locator="auth.py"),
                confidence=90,
            )
        )

        orchestrator = AdversarialPlanningOrchestrator(base_config)
        orchestrator.session.phase_0a_output = base_discovery
        orchestrator._select_mode()

        assert orchestrator.session.mode_selected == "deep"

    def test_privacy_risk_triggers_deep(self, base_config, base_discovery):
        """Test privacy_risk triggers deep mode."""
        base_discovery.evidence.append(
            Evidence(
                id="EV1",
                evidence_class=EvidenceClass.VERIFIED,
                claim="Privacy_risk: user data exposure possible",
                source=EvidenceSource(kind="file", locator="data.py"),
                confidence=90,
            )
        )

        orchestrator = AdversarialPlanningOrchestrator(base_config)
        orchestrator.session.phase_0a_output = base_discovery
        orchestrator._select_mode()

        assert orchestrator.session.mode_selected == "deep"

    def test_compliance_risk_triggers_deep(self, base_config, base_discovery):
        """Test compliance_risk triggers deep mode."""
        base_discovery.evidence.append(
            Evidence(
                id="EV1",
                evidence_class=EvidenceClass.VERIFIED,
                claim="Compliance_risk: GDPR requirements not met",
                source=EvidenceSource(kind="file", locator="privacy.py"),
                confidence=90,
            )
        )

        orchestrator = AdversarialPlanningOrchestrator(base_config)
        orchestrator.session.phase_0a_output = base_discovery
        orchestrator._select_mode()

        assert orchestrator.session.mode_selected == "deep"

    def test_legal_risk_triggers_deep(self, base_config, base_discovery):
        """Test legal_risk triggers deep mode."""
        base_discovery.evidence.append(
            Evidence(
                id="EV1",
                evidence_class=EvidenceClass.VERIFIED,
                claim="Legal_risk: licensing issue detected",
                source=EvidenceSource(kind="config", locator="LICENSE"),
                confidence=90,
            )
        )

        orchestrator = AdversarialPlanningOrchestrator(base_config)
        orchestrator.session.phase_0a_output = base_discovery
        orchestrator._select_mode()

        assert orchestrator.session.mode_selected == "deep"

    def test_three_unknowns_triggers_deep(self, base_config, base_discovery):
        """Test >2 critical unknowns triggers deep mode."""
        base_discovery.critical_unknowns = [
            CriticalUnknown(id="UNK1", question="Q1", why_it_matters="M1", fastest_probe="P1"),
            CriticalUnknown(id="UNK2", question="Q2", why_it_matters="M2", fastest_probe="P2"),
            CriticalUnknown(id="UNK3", question="Q3", why_it_matters="M3", fastest_probe="P3"),
        ]

        orchestrator = AdversarialPlanningOrchestrator(base_config)
        orchestrator.session.phase_0a_output = base_discovery
        orchestrator._select_mode()

        assert orchestrator.session.mode_selected == "deep"

    def test_two_unknowns_standard_mode(self, base_config, base_discovery):
        """Test exactly 2 critical unknowns stays in standard mode."""
        base_discovery.critical_unknowns = [
            CriticalUnknown(id="UNK1", question="Q1", why_it_matters="M1", fastest_probe="P1"),
            CriticalUnknown(id="UNK2", question="Q2", why_it_matters="M2", fastest_probe="P2"),
        ]

        orchestrator = AdversarialPlanningOrchestrator(base_config)
        orchestrator.session.phase_0a_output = base_discovery
        orchestrator._select_mode()

        assert orchestrator.session.mode_selected == "standard"

    def test_migration_problem_type_triggers_deep(self, base_config, base_discovery, base_scope):
        """Test problem_type=migration triggers deep mode."""
        base_scope.problem_type = "migration"

        orchestrator = AdversarialPlanningOrchestrator(base_config)
        orchestrator.session.phase_0a_output = base_discovery
        orchestrator.session.phase_0b_output = base_scope
        orchestrator._select_mode()

        assert orchestrator.session.mode_selected == "deep"

    def test_security_problem_type_triggers_deep(self, base_config, base_discovery, base_scope):
        """Test problem_type=security triggers deep mode."""
        base_scope.problem_type = "security"

        orchestrator = AdversarialPlanningOrchestrator(base_config)
        orchestrator.session.phase_0a_output = base_discovery
        orchestrator.session.phase_0b_output = base_scope
        orchestrator._select_mode()

        assert orchestrator.session.mode_selected == "deep"

    def test_same_model_fallback_triggers_deep(self, base_config, base_discovery):
        """Test same-model fallback triggers deep mode."""
        orchestrator = AdversarialPlanningOrchestrator(base_config)
        orchestrator.session.phase_0a_output = base_discovery
        orchestrator.session.same_model_fallback = True
        orchestrator._select_mode()

        assert orchestrator.session.mode_selected == "deep"

    def test_no_triggers_selects_standard(self, base_config, base_discovery, base_scope):
        """Test standard mode when no triggers present."""
        orchestrator = AdversarialPlanningOrchestrator(base_config)
        orchestrator.session.phase_0a_output = base_discovery
        orchestrator.session.phase_0b_output = base_scope
        orchestrator._select_mode()

        assert orchestrator.session.mode_selected == "standard"

    def test_case_insensitive_trigger_matching(self, base_config, base_discovery):
        """Test trigger matching is case insensitive in evidence claim."""
        base_discovery.evidence.append(
            Evidence(
                id="EV1",
                evidence_class=EvidenceClass.VERIFIED,
                claim="This involves PRODUCTION_CHANGE deployment",  # Uppercase
                source=EvidenceSource(kind="file", locator="deploy.yml"),
                confidence=90,
            )
        )

        orchestrator = AdversarialPlanningOrchestrator(base_config)
        orchestrator.session.phase_0a_output = base_discovery
        orchestrator._select_mode()

        assert orchestrator.session.mode_selected == "deep"


class TestModeSelectionEmit:
    """Test mode selection emits progress events."""

    def test_deep_mode_emits_triggers(self, sample_config, sample_phase_0a_output):
        """Test deep mode selection emits triggers list."""
        sample_config.mode = "auto"
        from unittest.mock import MagicMock
        mock_emit = MagicMock()

        orchestrator = AdversarialPlanningOrchestrator(
            sample_config,
            emit_progress_fn=mock_emit,
        )

        # Add trigger
        sample_phase_0a_output.critical_unknowns = [
            CriticalUnknown(id="UNK1", question="Q1", why_it_matters="M1", fastest_probe="P1"),
            CriticalUnknown(id="UNK2", question="Q2", why_it_matters="M2", fastest_probe="P2"),
            CriticalUnknown(id="UNK3", question="Q3", why_it_matters="M3", fastest_probe="P3"),
        ]
        orchestrator.session.phase_0a_output = sample_phase_0a_output

        orchestrator._select_mode()

        # Check emit was called with mode_selected event
        mock_emit.assert_called()
        call_args = mock_emit.call_args
        assert call_args[0][0] == "mode_selected"
        assert call_args[0][1]["mode"] == "deep"
        assert len(call_args[0][1]["triggers"]) > 0

    def test_standard_mode_emits_empty_triggers(self, sample_config, sample_phase_0a_output, sample_phase_0b_output):
        """Test standard mode emits empty triggers list."""
        sample_config.mode = "auto"
        from unittest.mock import MagicMock
        mock_emit = MagicMock()

        orchestrator = AdversarialPlanningOrchestrator(
            sample_config,
            emit_progress_fn=mock_emit,
        )

        orchestrator.session.phase_0a_output = sample_phase_0a_output
        orchestrator.session.phase_0b_output = sample_phase_0b_output

        orchestrator._select_mode()

        # Check emit was called with mode_selected event
        mock_emit.assert_called()
        call_args = mock_emit.call_args
        assert call_args[0][0] == "mode_selected"
        assert call_args[0][1]["mode"] == "standard"
        assert call_args[0][1]["triggers"] == []


class TestForcedModes:
    """Test forced mode selection."""

    def test_forced_standard_overrides_triggers(self, sample_config, sample_phase_0a_output):
        """Test forced standard mode overrides any triggers."""
        sample_config.mode = "standard"

        orchestrator = AdversarialPlanningOrchestrator(sample_config)

        # Add triggers that would normally trigger deep mode
        sample_phase_0a_output.evidence.append(
            Evidence(
                id="EV1",
                evidence_class=EvidenceClass.VERIFIED,
                claim="security_risk: potential vulnerability",
                source=EvidenceSource(kind="file", locator="auth.py"),
                confidence=90,
            )
        )
        sample_phase_0a_output.critical_unknowns = [
            CriticalUnknown(id="UNK1", question="Q1", why_it_matters="M1", fastest_probe="P1"),
            CriticalUnknown(id="UNK2", question="Q2", why_it_matters="M2", fastest_probe="P2"),
            CriticalUnknown(id="UNK3", question="Q3", why_it_matters="M3", fastest_probe="P3"),
        ]

        orchestrator.session.phase_0a_output = sample_phase_0a_output
        orchestrator._select_mode()

        # Forced standard overrides
        assert orchestrator.session.mode_selected == "standard"

    def test_forced_deep_overrides_clean(self, sample_config, sample_phase_0a_output, sample_phase_0b_output):
        """Test forced deep mode even without triggers."""
        sample_config.mode = "deep"

        orchestrator = AdversarialPlanningOrchestrator(sample_config)
        orchestrator.session.phase_0a_output = sample_phase_0a_output
        orchestrator.session.phase_0b_output = sample_phase_0b_output
        orchestrator._select_mode()

        assert orchestrator.session.mode_selected == "deep"
