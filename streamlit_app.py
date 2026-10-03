import asyncio
from io import BytesIO

import streamlit as st
from fastapi import UploadFile
from starlette.datastructures import Headers

from recruit_assistant.models import CandidateProfileInput, ResearchRequest
from recruit_assistant.research import run_research
from recruit_assistant.storage import create_job_intake, get_job


st.set_page_config(
    page_title="Evidence-First Recruiting Assistant",
    page_icon="🔎",
    layout="wide",
)

UI_SCHEMA_VERSION = 2
if st.session_state.get("_ui_schema_version") != UI_SCHEMA_VERSION:
    st.session_state.pop("research_run", None)
    st.session_state["_ui_schema_version"] = UI_SCHEMA_VERSION


def create_intake(
    job_name: str,
    job_description: str,
    uploaded_files: list,
    research_consent: bool,
):
    uploads = [
        UploadFile(
            file=BytesIO(uploaded.getvalue()),
            filename=uploaded.name,
            size=uploaded.size,
            headers=Headers(
                {"content-type": uploaded.type or "application/octet-stream"}
            ),
        )
        for uploaded in uploaded_files
    ]
    return asyncio.run(
        create_job_intake(
            job_name,
            job_description,
            uploads,
            professional_research_consent=research_consent,
        )
    )


def show_source(source) -> None:
    label = f"{source.platform.title()} · {source.status.replace('_', ' ')}"
    st.markdown(f"**{label}**")
    st.caption(source.url)
    for signal in getattr(source, "match_signals", []):
        st.markdown(f"- {signal}")
    if source.job_relevant_excerpt:
        st.text(source.job_relevant_excerpt)
    if source.error:
        st.warning(source.error)


def show_fit_analysis(analysis) -> None:
    decision = getattr(analysis, "decision", None)
    if decision:
        score_text = (
            f"{decision.evidence_score:.1f}/100"
            if decision.evidence_score is not None
            else "Unavailable"
        )
        score_column, required_column, preferred_column, coverage_column = st.columns(4)
        score_column.metric("Strict rubric match score", score_text)
        required_score = getattr(decision, "required_criteria_score", None)
        required_column.metric(
            "Required criteria",
            f"{required_score:.1f}/100" if required_score is not None else "N/A",
            help=(
                f"{getattr(decision, 'required_criteria_met', 0)} of "
                f"{getattr(decision, 'required_criteria_total', 0)} required "
                "criteria have sufficient evidence."
            ),
        )
        preferred_score = getattr(decision, "preferred_criteria_score", None)
        preferred_column.metric(
            "Preferred criteria",
            f"{preferred_score:.1f}/100" if preferred_score is not None else "N/A",
        )
        coverage_column.metric(
            "Evidence coverage",
            f"{decision.evidence_coverage:.0f}%",
            help="Available evidence weight, not a measure of candidate quality.",
        )
        st.caption(
            "Scoring guide: 80+ indicates strong demonstrated alignment when required "
            "criteria are supported; 35+ indicates potential alignment for human review. "
            "Explicit hard-requirement gaps or conflicting evidence remain review cases."
        )

        labels = {
            "strong_role_alignment": "Strong demonstrated alignment",
            "potential_role_alignment": "Potential alignment — review needed",
            "insufficient_demonstrated_evidence": (
                "Insufficient demonstrated evidence — review needed"
            ),
            "analysis_unavailable": "Analysis unavailable — review needed",
        }
        if decision.fit_label == "strong_role_alignment":
            st.success(labels[decision.fit_label])
        else:
            st.warning(labels[decision.fit_label])
        if getattr(decision, "hard_requirement_gaps", None):
            st.error("Required qualification not met")
            for gap in decision.hard_requirement_gaps:
                st.markdown(f"- {gap}")
        experience = getattr(decision, "experience_check", None)
        if experience:
            with st.expander("Deterministic experience check"):
                st.write(
                    f"Required: **{experience.required_years:g} years**"
                    if experience.required_years is not None
                    else "No numeric experience requirement detected."
                )
                st.write(
                    f"Resume statement: **{experience.stated_years:g} years**"
                    if experience.stated_years is not None
                    else "No explicit years-of-experience statement detected."
                )
                st.write(
                    f"Calculated from dated work history: "
                    f"**{experience.calculated_years:g} years**"
                    if experience.calculated_years is not None
                    else "Dated work history could not be calculated."
                )
                st.caption(
                    "Overlapping roles are counted once. The more favorable supported "
                    "value is used so incomplete date extraction does not penalize a "
                    "candidate."
                )
        if decision.top_30_percent:
            st.info(
                f"Top 30% of current evidence scores · review rank "
                f"{decision.shortlist_rank}"
            )
    elif analysis.route == "advance_for_human_review":
        st.success("Strong evidence — advance for human review")
    else:
        st.warning("Human review required")

    st.write(analysis.summary)
    if analysis.strengths:
        st.markdown("**Evidence-backed strengths**")
        for strength in analysis.strengths:
            st.markdown(f"- {strength}")
    if analysis.unknowns:
        st.markdown("**Unknown or missing evidence**")
        for unknown in analysis.unknowns:
            st.markdown(f"- {unknown}")

    if decision and decision.source_assessments:
        with st.expander("Evidence quality by source"):
            for source in decision.source_assessments:
                value = (
                    f"{source.score:.0f}/100"
                    if source.score is not None
                    else "Unknown"
                )
                st.markdown(
                    f"**{source.source.title()} — {value} "
                    f"(weight {source.weight:.0f}%)**"
                )
                st.write(source.rationale)
                for quote in source.evidence:
                    st.markdown(f"> {quote}")

    for criterion in analysis.criteria:
        requirement = "required" if criterion.required else "preferred"
        with st.expander(
            f"{criterion.criterion} · {criterion.assessment} · {requirement} · "
            f"{getattr(criterion, 'weight', 0):.1f}%"
        ):
            st.caption(f"Confidence: {criterion.confidence:.0%}")
            if criterion.evidence:
                for quote in criterion.evidence:
                    st.markdown(f"> {quote}")
            else:
                st.write("No supporting excerpt was available.")


st.title("Evidence-First Recruiting Assistant")
st.write(
    "Upload a job and candidate resumes. The assistant finds job-relevant "
    "professional evidence while keeping every employment decision with a person."
)
st.info(
    "No candidate is rejected automatically. Missing or unavailable evidence is "
    "treated as unknown and routed to review."
)

with st.form("job_intake"):
    job_name = st.text_input(
        "Job name",
        placeholder="Senior Backend Engineer",
        max_chars=200,
    )
    job_description = st.text_area(
        "Job description",
        placeholder="Paste the complete role description and requirements.",
        height=220,
        max_chars=50_000,
    )
    resumes = st.file_uploader(
        "Resumes",
        type=["pdf", "docx", "doc", "txt"],
        accept_multiple_files=True,
        help="Upload 1–20 files, up to 10 MB each.",
    )
    research_consent = st.checkbox(
        "I confirm candidates received notice or consented to public professional-"
        "profile discovery and research."
    )
    submitted = st.form_submit_button(
        "Save job and resumes",
        type="primary",
        use_container_width=True,
    )

if submitted:
    if not 1 <= len(resumes) <= 20:
        st.error("Upload between 1 and 20 resumes.")
    else:
        try:
            with st.spinner("Reading and saving resumes locally…"):
                job = create_intake(
                    job_name,
                    job_description,
                    resumes,
                    research_consent,
                )
            st.session_state["job_id"] = job.job_id
            st.session_state.pop("research_run", None)
            st.success(f"Saved {job.resume_count} resumes for {job.job_name}.")
        except Exception as exc:
            st.error(f"Could not save the job intake: {exc}")

job_id = st.session_state.get("job_id")
if job_id:
    job = get_job(job_id)
    st.divider()
    st.subheader("Uploaded candidates")
    st.caption(f"Job ID: {job.job_id}")

    can_research = job.professional_research_consent
    if not can_research:
        st.warning(
            "Professional-profile research is disabled because notice/consent was "
            "not confirmed during intake."
        )

    if st.button(
        "Find public profiles and analyze candidates",
        type="primary",
        disabled=not can_research,
        use_container_width=True,
    ):
        try:
            with st.spinner(
                "Searching the public web, checking professional sources, and asking "
                "local Qwen to organize the evidence…"
            ):
                st.session_state["research_run"] = run_research(
                    job,
                    ResearchRequest(consent_confirmed=True),
                )
        except Exception as exc:
            st.error(f"Research could not be completed: {exc}")

    for resume in job.resumes:
        icon = "✅" if resume.parsing_status == "complete" else "⚠️"
        with st.expander(f"{icon} {resume.original_filename}"):
            st.write(f"Text extraction: **{resume.parsing_status}**")
            if resume.parsing_error:
                st.warning(resume.parsing_error)
            if resume.extracted_links:
                st.markdown("**Candidate-provided professional profiles**")
                for link in resume.extracted_links:
                    st.markdown(f"- [{link}]({link})")
            else:
                st.write(
                    "No profile URL was present in this resume. Full-web profile "
                    "discovery is available from the button above."
                )

run = st.session_state.get("research_run")
if run:
    st.divider()
    st.subheader("Evidence review")
    st.caption(run.safety_notice)
    suggestions = [
        (candidate, source)
        for candidate in run.candidates
        for source in candidate.sources
        if source.status == "needs_identity_review"
    ]
    if suggestions:
        st.warning(
            "These profile matches are suggestions, not verified identities. They are "
            "excluded from analysis and scoring unless you confirm them."
        )
        selected_suggestions = []
        suggestion_groups = {}
        for candidate, source in suggestions:
            suggestion_groups.setdefault(
                (candidate.resume_id, candidate.original_filename, source.platform),
                [],
            ).append((candidate, source))
        with st.form("profile_confirmation"):
            for (
                resume_id,
                original_filename,
                platform,
            ), group in suggestion_groups.items():
                st.markdown(f"**{original_filename} · {platform.title()}**")
                options = ["Do not confirm"] + [
                    source.url for _, source in group
                ]
                selected_url = st.radio(
                    "Choose only after checking that the profile belongs to the candidate",
                    options,
                    key=f"confirm_{resume_id}_{platform}",
                )
                for _, source in group:
                    st.caption(
                        f"{source.url} — {'; '.join(source.match_signals)}"
                    )
                if selected_url != "Do not confirm":
                    selected_suggestions.append(
                        next(
                            item
                            for item in group
                            if item[1].url == selected_url
                        )
                    )
            confirm_profiles = st.form_submit_button(
                "Confirm selected identities and rerun analysis",
                type="primary",
                disabled=not selected_suggestions,
            )
        if confirm_profiles:
            profiles_by_resume: dict[str, dict[str, str]] = {}
            for candidate, source in selected_suggestions:
                profiles_by_resume.setdefault(candidate.resume_id, {})[
                    f"{source.platform}_url"
                ] = source.url
            confirmed_candidates = [
                CandidateProfileInput(
                    resume_id=resume_id,
                    identity_confirmed=True,
                    **profiles,
                )
                for resume_id, profiles in profiles_by_resume.items()
            ]
            with st.spinner("Researching confirmed profiles and rerunning analysis…"):
                st.session_state["research_run"] = run_research(
                    job,
                    ResearchRequest(
                        consent_confirmed=True,
                        candidates=confirmed_candidates,
                    ),
                )
            st.rerun()

    rubric = getattr(run, "rubric", None)
    if rubric:
        with st.expander("Role-specific rubric used for every candidate"):
            for criterion in rubric.criteria:
                requirement = "Required" if criterion.required else "Preferred"
                st.markdown(
                    f"**{criterion.title} · {criterion.weight:.1f}% · "
                    f"{requirement}**"
                )
                st.write(criterion.description)

    shortlisted = [
        candidate
        for candidate in run.candidates
        if getattr(candidate.fit_analysis, "decision", None)
        and candidate.fit_analysis.decision.top_30_percent
    ]
    if shortlisted:
        st.markdown("### Top 30% for human review")
        st.write(
            "These candidates have the strongest currently demonstrated, "
            "role-specific evidence. This is not an automatic hiring decision."
        )
        for candidate in sorted(
            shortlisted,
            key=lambda item: item.fit_analysis.decision.shortlist_rank or 999,
        ):
            decision = candidate.fit_analysis.decision
            st.markdown(
                f"- **#{decision.shortlist_rank} {candidate.original_filename}** — "
                f"{decision.evidence_score:.1f}/100"
            )

    ordered_candidates = sorted(
        run.candidates,
        key=lambda item: (
            bool(
                getattr(item.fit_analysis, "decision", None)
                and item.fit_analysis.decision.top_30_percent
            ),
            (
                item.fit_analysis.decision.evidence_score
                if getattr(item.fit_analysis, "decision", None)
                and item.fit_analysis.decision.evidence_score is not None
                else -1
            ),
        ),
        reverse=True,
    )
    for candidate in ordered_candidates:
        with st.container(border=True):
            st.markdown(f"### {candidate.original_filename}")
            if candidate.sources:
                with st.expander("Professional sources"):
                    for source in candidate.sources:
                        show_source(source)
            else:
                st.caption(
                    "No candidate-provided professional profile was available. "
                    "The resume was assessed on its own."
                )
            show_fit_analysis(candidate.fit_analysis)
