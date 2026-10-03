from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

from recruit_assistant.extraction import (
    extract_embedded_professional_links,
    extract_professional_links,
    normalize_text,
)
from recruit_assistant.local_llm import (
    _calculate_work_history_years,
    analyze_fit,
    build_job_rubric,
)
from recruit_assistant.main import app
from recruit_assistant.models import (
    CandidateDecision,
    CandidateResearch,
    FitAnalysis,
    IdentityHints,
    JobRubric,
    RubricCriterion,
    SourceEvidence,
)
from recruit_assistant.research import (
    _apply_shortlist,
    _linkedin_profile_from_activity,
    _profile_match_signals,
    _suggestion_signals,
)


def test_extracts_only_professional_profile_links() -> None:
    text = """
    Portfolio: https://example.com/person
    GitHub: github.com/octocat
    LinkedIn: https://www.linkedin.com/in/example-person/
    Repository: https://github.com/octocat/Hello-World
    """
    assert extract_professional_links(text) == [
        "https://github.com/octocat",
        "https://github.com/octocat/Hello-World",
        "https://linkedin.com/in/example-person",
    ]


def test_normalizes_resume_text() -> None:
    assert normalize_text(" First   line \n\n Second\tline ") == (
        "First line\nSecond line"
    )


def test_extracts_embedded_pdf_professional_links() -> None:
    output = BytesIO()
    pdf = canvas.Canvas(output)
    pdf.drawString(72, 720, "LinkedIn | GitHub")
    pdf.linkURL(
        "https://www.linkedin.com/in/example-person/",
        (72, 710, 180, 735),
    )
    pdf.linkURL(
        "https://github.com/example-person",
        (190, 710, 290, 735),
    )
    pdf.save()

    assert extract_embedded_professional_links(output.getvalue(), ".pdf") == [
        "https://github.com/example-person",
        "https://linkedin.com/in/example-person",
    ]


def test_calculates_non_overlapping_work_history() -> None:
    resume = """
    WORK EXPERIENCE
    Backend Engineer
    May 2021 - Dec 2024
    Concurrent consulting project
    Jan 2023 - Jun 2023
    EDUCATION
    2018 - 2020
    """

    assert _calculate_work_history_years(resume) == 3.7


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.chdir(tmp_path)
    return TestClient(app)


def test_intake_extracts_text_and_requires_research_consent(
    client: TestClient,
) -> None:
    intake = client.post(
        "/jobs/intake",
        data={
            "job_name": "Backend Engineer",
            "job_description": "Python is required.",
        },
        files={
            "resumes": (
                "candidate.txt",
                b"Candidate\nGitHub: https://github.com/octocat\nPython",
                "text/plain",
            )
        },
    )
    assert intake.status_code == 201
    job = intake.json()["job"]
    assert job["resumes"][0]["parsing_status"] == "complete"
    assert job["resumes"][0]["extracted_links"] == [
        "https://github.com/octocat"
    ]

    denied = client.post(
        f"/jobs/{job['job_id']}/research",
        json={"consent_confirmed": False},
    )
    assert denied.status_code == 422
    assert "consent" in denied.json()["detail"].lower()


def test_research_without_profile_links_uses_human_review(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    intake = client.post(
        "/jobs/intake",
        data={
            "job_name": "Backend Engineer",
            "job_description": "Python is required.",
        },
        files={
            "resumes": (
                "candidate.txt",
                b"Candidate\nBuilt APIs with Python.",
                "text/plain",
            )
        },
    ).json()["job"]

    monkeypatch.setattr(
        "recruit_assistant.research.analyze_fit",
        lambda *_: FitAnalysis(
            status="complete",
            route="advance_for_human_review",
            summary="Python evidence is present.",
        ),
    )
    response = client.post(
        f"/jobs/{intake['job_id']}/research",
        json={"consent_confirmed": True},
    )
    assert response.status_code == 200
    run = response.json()["run"]
    assert run["candidates"][0]["sources"] == []
    assert (
        run["candidates"][0]["fit_analysis"]["route"]
        == "advance_for_human_review"
    )
    assert Path(
        f".data/jobs/{intake['job_id']}/research/{run['run_id']}.json"
    ).exists()


def test_corrupted_pdf_is_saved_with_actionable_parsing_error(
    client: TestClient,
) -> None:
    response = client.post(
        "/jobs/intake",
        data={
            "job_name": "Backend Engineer",
            "job_description": "Python is required.",
        },
        files={
            "resumes": (
                "broken.pdf",
                b"\x89PNG\r\n\x1a\nnot-a-pdf",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 201
    resume = response.json()["job"]["resumes"][0]
    assert resume["parsing_status"] == "failed"
    assert "Invalid or corrupted PDF" in resume["parsing_error"]


def test_manager_supplied_url_requires_identity_confirmation() -> None:
    with TestClient(app) as test_client:
        response = test_client.post(
            "/jobs/not-used/research",
            json={
                "consent_confirmed": True,
                "candidates": [
                    {
                        "resume_id": "resume",
                        "github_url": "https://github.com/octocat",
                        "identity_confirmed": False,
                    }
                ],
            },
        )
    assert response.status_code == 422


def test_profile_discovery_requires_name_and_corroborating_signal() -> None:
    hints = IdentityHints(
        full_name="Alex Morgan",
        locations=["Boston, Massachusetts"],
        roles=["Distributed Systems Engineer"],
        employers=["Example Labs"],
    )

    assert _profile_match_signals(
        hints,
        {
            "name": "Alex Morgan",
            "location": "Boston, MA",
            "company": "Unrelated Company",
            "bio": "Distributed systems builder",
        },
    ) == [
        "Public profile name matches the resume name",
        "Public profile location matches a resume location",
        "Public profile role matches a resume role",
    ]
    assert _profile_match_signals(
        hints,
        {
            "name": "Alex Morgan",
            "location": "Seattle",
            "company": "Another Company",
            "bio": "Software engineer",
        },
    ) == ["Public profile name matches the resume name"]
    assert _profile_match_signals(
        hints,
        {
            "name": "Different Person",
            "location": "Boston",
            "company": "Example Labs",
        },
    ) == []
    name_only = ["Public profile name matches the resume name"]
    assert _suggestion_signals(name_only) == []
    assert _linkedin_profile_from_activity(
        "https://linkedin.com/posts/deepika-kubendira-rao-123_activity-456",
        "Deepika Kubendira Rao",
    ) == "https://linkedin.com/in/deepika-kubendira-rao-123"
    assert (
        _linkedin_profile_from_activity(
            "https://linkedin.com/posts/another-person_activity-456",
            "Deepika Kubendira Rao",
        )
        is None
    )


def test_fit_policy_advances_only_supported_required_criteria(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "recruit_assistant.local_llm.complete_json",
        lambda *_args, **_kwargs: {
            "summary": "The supplied evidence supports the required criterion.",
            "strengths": ["Built production Python APIs."],
            "unknowns": [],
            "criteria": [
                {
                    "criterion_id": "production_python",
                    "criterion": "Production Python",
                    "required": True,
                    "assessment": "demonstrated",
                    "evidence": ["Built production Python APIs"],
                    "confidence": 0.91,
                }
            ],
            "source_assessments": [
                {
                    "source": "resume",
                    "assessment": "strong",
                    "rationale": "Direct production Python experience.",
                    "evidence": ["Built production Python APIs"],
                },
                {
                    "source": "projects",
                    "assessment": "moderate",
                    "rationale": "Relevant API project evidence.",
                    "evidence": ["Built APIs"],
                },
            ],
        },
    )
    rubric = JobRubric(
        model="qwen",
        criteria=[
            RubricCriterion(
                criterion_id="production_python",
                title="Production Python",
                description="Evidence of production Python work.",
                required=True,
                weight=100,
            )
        ],
    )
    result = analyze_fit(
        "Production Python is required.",
        "Built production Python APIs.",
        [],
        rubric,
    )
    assert result.route == "advance_for_human_review"
    assert result.criteria[0].required is True
    assert result.decision.evidence_score == pytest.approx(91.0)
    assert result.decision.fit_label == "strong_role_alignment"


def test_demonstrated_evidence_recovers_placeholder_zero_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "recruit_assistant.local_llm.complete_json",
        lambda *_args, **_kwargs: {
            "summary": "The supplied evidence directly supports the criterion.",
            "strengths": ["Built production RAG agents."],
            "unknowns": [],
            "criteria": [
                {
                    "criterion_id": "rag_agents",
                    "assessment": "demonstrated",
                    "evidence": ["Built RAG agents using LangGraph"],
                    "confidence": 0.0,
                }
            ],
            "source_assessments": [
                {
                    "source": "resume",
                    "assessment": "strong",
                    "rationale": "Direct RAG evidence.",
                    "evidence": ["Built RAG agents using LangGraph"],
                }
            ],
        },
    )
    rubric = JobRubric(
        model="qwen",
        criteria=[
            RubricCriterion(
                criterion_id="rag_agents",
                title="RAG agents",
                description="Direct evidence of RAG agent development.",
                required=True,
                weight=100,
            )
        ],
    )

    result = analyze_fit(
        "RAG agent development is required.",
        "Built RAG agents using LangGraph.",
        [],
        rubric,
    )

    assert result.criteria[0].confidence == pytest.approx(0.95)
    assert result.decision.evidence_score == pytest.approx(95.0)
    assert result.decision.required_criteria_supported is True
    assert result.decision.fit_label == "strong_role_alignment"


def test_positive_excerpt_recovers_unknown_as_partial_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "recruit_assistant.local_llm.complete_json",
        lambda *_args, **_kwargs: {
            "summary": "The candidate has adjacent project evidence.",
            "strengths": ["Built a related agent prototype."],
            "unknowns": [],
            "criteria": [
                {
                    "criterion_id": "agent_systems",
                    "assessment": "unknown",
                    "evidence": ["Built an agent prototype in Python"],
                    "confidence": 0.0,
                }
            ],
            "source_assessments": [
                {
                    "source": "resume",
                    "assessment": "moderate",
                    "rationale": "Adjacent project evidence.",
                    "evidence": ["Built an agent prototype in Python"],
                }
            ],
        },
    )
    rubric = JobRubric(
        model="qwen",
        criteria=[
            RubricCriterion(
                criterion_id="agent_systems",
                title="Agent systems",
                description="Experience building production agent systems.",
                required=True,
                weight=100,
            )
        ],
    )

    result = analyze_fit(
        "Agent-system experience is required.",
        "Built an agent prototype in Python.",
        [],
        rubric,
    )

    assert result.criteria[0].assessment == "partial"
    assert result.criteria[0].confidence == pytest.approx(0.65)
    assert result.decision.evidence_score == pytest.approx(45.5)
    assert result.decision.required_criteria_supported is True
    assert result.decision.fit_label == "potential_role_alignment"


def test_negative_unknown_evidence_remains_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "recruit_assistant.local_llm.complete_json",
        lambda *_args, **_kwargs: {
            "summary": "No agent evidence was supplied.",
            "criteria": [
                {
                    "criterion_id": "agent_systems",
                    "assessment": "unknown",
                    "evidence": ["No explicit evidence of production agent systems."],
                    "confidence": 0.0,
                }
            ],
            "source_assessments": [
                {
                    "source": "resume",
                    "assessment": "weak",
                    "rationale": "No relevant evidence.",
                    "evidence": [],
                }
            ],
        },
    )
    rubric = JobRubric(
        model="qwen",
        criteria=[
            RubricCriterion(
                criterion_id="agent_systems",
                title="Agent systems",
                description="Production agent-system evidence.",
                required=True,
                weight=100,
            )
        ],
    )

    result = analyze_fit(
        "Production agent-system experience is required.",
        "Backend software engineer.",
        [],
        rubric,
    )

    assert result.criteria[0].assessment == "unknown"
    assert result.criteria[0].confidence == 0.0
    assert result.decision.evidence_score == 0.0
    assert result.decision.required_criteria_supported is False


def test_direct_criterion_excerpt_recovers_unknown_as_demonstrated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "recruit_assistant.local_llm.complete_json",
        lambda *_args, **_kwargs: {
            "summary": "Direct pipeline evidence was supplied.",
            "criteria": [
                {
                    "criterion_id": "data_ai_pipelines",
                    "assessment": "unknown",
                    "evidence": [
                        "Built end-to-end data and AI pipelines using Python and SQL."
                    ],
                    "confidence": 0.0,
                }
            ],
            "source_assessments": [
                {
                    "source": "resume",
                    "assessment": "strong",
                    "rationale": "Direct pipeline evidence.",
                    "evidence": [
                        "Built end-to-end data and AI pipelines using Python and SQL."
                    ],
                }
            ],
        },
    )
    rubric = JobRubric(
        model="qwen",
        criteria=[
            RubricCriterion(
                criterion_id="data_ai_pipelines",
                title="Data and AI Pipeline Development",
                description="End-to-end data and AI pipeline evidence.",
                required=True,
                weight=100,
            )
        ],
    )

    result = analyze_fit(
        "Data and AI pipeline development is required.",
        "Built end-to-end data and AI pipelines using Python and SQL.",
        [],
        rubric,
    )

    assert result.criteria[0].assessment == "demonstrated"
    assert result.criteria[0].confidence == pytest.approx(0.90)
    assert result.decision.evidence_score == pytest.approx(90.0)
    assert result.decision.fit_label == "strong_role_alignment"


def test_rubric_replaces_duplicate_placeholder_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "recruit_assistant.local_llm.complete_json",
        lambda *_args, **_kwargs: {
            "criteria": [
                {
                    "criterion_id": "short_id",
                    "title": "Professional Experience",
                    "description": "Required tenure",
                    "required": True,
                    "weight": 60,
                },
                {
                    "criterion_id": "short_id",
                    "title": "Backend Systems",
                    "description": "Backend evidence",
                    "required": True,
                    "weight": 40,
                },
            ]
        },
    )

    rubric = build_job_rubric("Backend role")

    assert [item.criterion_id for item in rubric.criteria] == [
        "professional_experience",
        "backend_systems",
    ]


def test_unconfirmed_profile_is_excluded_from_scoring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "recruit_assistant.local_llm.complete_json",
        lambda *_args, **_kwargs: {
            "summary": "Resume-only assessment.",
            "strengths": [],
            "unknowns": ["GitHub identity is unconfirmed."],
            "criteria": [],
            "source_assessments": [
                {
                    "source": "github",
                    "assessment": "strong",
                    "rationale": "Must be ignored until identity confirmation.",
                    "evidence": ["Public repository"],
                }
            ],
        },
    )
    rubric = JobRubric(
        model="qwen",
        criteria=[
            RubricCriterion(
                criterion_id="backend",
                title="Backend engineering",
                description="Backend evidence",
                required=True,
                weight=100,
            )
        ],
    )
    suggestion = SourceEvidence(
        platform="github",
        url="https://github.com/suggested",
        retrieved_at="2026-10-03T00:00:00+00:00",
        status="needs_identity_review",
        identity_basis="unverified",
        match_signals=["Public profile name matches the resume name"],
    )

    result = analyze_fit(
        "Backend engineering is required.",
        "Built backend APIs.",
        [suggestion],
        rubric,
    )

    github = next(
        source
        for source in result.decision.source_assessments
        if source.source == "github"
    )
    assert github.assessment == "unknown"
    assert github.score is None


def test_explicit_years_shortfall_is_a_hard_requirement_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "recruit_assistant.local_llm.complete_json",
        lambda *_args, **_kwargs: {
            "summary": "Relevant backend work, but below the required tenure.",
            "strengths": ["Backend development"],
            "unknowns": [],
            "criteria": [
                {
                    "criterion_id": "professional_experience",
                    "assessment": "demonstrated",
                    "evidence": ["4 years of experience"],
                    "confidence": 0.95,
                }
            ],
            "source_assessments": [
                {
                    "source": "resume",
                    "assessment": "strong",
                    "rationale": "Relevant backend evidence.",
                    "evidence": ["Backend systems"],
                }
            ],
        },
    )
    rubric = JobRubric(
        model="qwen",
        criteria=[
            RubricCriterion(
                criterion_id="professional_experience",
                title="Professional experience",
                description="At least six years.",
                required=True,
                weight=100,
            )
        ],
    )

    result = analyze_fit(
        "Required Qualifications: 6+ years of professional software development "
        "experience.",
        "Software engineer with 4 years of professional experience.",
        [],
        rubric,
    )

    assert result.decision.evidence_score == 49.0
    assert result.decision.required_criteria_supported is False
    assert result.decision.fit_label == "insufficient_demonstrated_evidence"
    assert result.decision.hard_requirement_gaps == [
        "Requires 6+ years of experience; resume evidence supports 4 years "
        "(resume statement: 4 years)."
    ]
    assert result.decision.required_criteria_score == pytest.approx(95.0)
    assert result.decision.preferred_criteria_score is None
    assert result.decision.required_criteria_met == 1
    assert result.decision.required_criteria_total == 1
    assert result.decision.experience_check.required_years == 6
    assert result.decision.experience_check.stated_years == 4


def test_shortlist_selects_top_thirty_percent_with_ties() -> None:
    candidates = []
    for index, score in enumerate([92.0, 85.0, 85.0, 60.0]):
        candidates.append(
            CandidateResearch(
                resume_id=str(index),
                original_filename=f"candidate-{index}.pdf",
                sources=[],
                fit_analysis=FitAnalysis(
                    status="complete",
                    route="human_review_required",
                    summary="Test",
                    decision=CandidateDecision(
                        evidence_score=score,
                        evidence_coverage=70,
                        fit_label="potential_role_alignment",
                        required_criteria_supported=True,
                    ),
                ),
            )
        )

    selected_count = _apply_shortlist(candidates)

    assert selected_count == 3
    assert [candidate.fit_analysis.decision.top_30_percent for candidate in candidates] == [
        True,
        True,
        True,
        False,
    ]
