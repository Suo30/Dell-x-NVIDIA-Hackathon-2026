import hashlib
import json
import math
import re
import shutil
import subprocess
import uuid
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from fastapi import HTTPException, status

from recruit_assistant.config import USER_AGENT, WEB_REQUEST_TIMEOUT_SECONDS
from recruit_assistant.local_llm import (
    LocalModelUnavailable,
    analyze_fit,
    build_job_rubric,
    extract_identity_hints,
    sanitize_linkedin_evidence,
)
from recruit_assistant.models import (
    CandidateProfileInput,
    CandidateResearch,
    IdentityHints,
    JobIntake,
    ResearchRequest,
    ResearchRun,
    SourceEvidence,
    utc_now_iso,
)
from recruit_assistant.storage import get_resume_text, write_research_run


def run_research(job: JobIntake, request: ResearchRequest) -> ResearchRun:
    if not request.consent_confirmed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Explicit consent/notice confirmation is required before professional "
                "web research."
            ),
        )

    resumes_by_id = {resume.resume_id: resume for resume in job.resumes}
    supplied = {candidate.resume_id: candidate for candidate in request.candidates}
    unknown_ids = sorted(set(supplied) - set(resumes_by_id))
    if unknown_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown resume IDs: {', '.join(unknown_ids)}",
        )

    try:
        rubric = build_job_rubric(job.job_description)
    except LocalModelUnavailable:
        rubric = None

    candidates: list[CandidateResearch] = []
    for resume in job.resumes:
        profiles: dict[
            Literal["github", "linkedin"],
            tuple[str, Literal["resume_link", "manager_confirmed"]],
        ] = {}

        if request.use_candidate_provided_links:
            for url in resume.extracted_links:
                platform = _platform_for_url(url)
                if platform:
                    profiles[platform] = (url, "resume_link")

        supplied_candidate = supplied.get(resume.resume_id)
        if supplied_candidate:
            _add_confirmed_profiles(profiles, supplied_candidate)

        resume_text = get_resume_text(job.job_id, resume)
        evidence = [
            _research_source(platform, url, basis, job.job_description)
            for platform, (url, basis) in profiles.items()
        ]
        if request.discover_public_profiles and resume_text:
            evidence.extend(
                _discover_profile_suggestions(resume_text, set(profiles))
            )
        candidates.append(
            CandidateResearch(
                resume_id=resume.resume_id,
                original_filename=resume.original_filename,
                sources=evidence,
                fit_analysis=analyze_fit(
                    job.job_description,
                    resume_text,
                    evidence,
                    rubric,
                ),
            )
        )

    shortlist_count = _apply_shortlist(candidates)
    run = ResearchRun(
        run_id=str(uuid.uuid4()),
        job_id=job.job_id,
        created_at=utc_now_iso(),
        rubric=rubric,
        shortlist_count=shortlist_count,
        candidates=candidates,
    )
    write_research_run(job.job_id, run.run_id, run.model_dump_json(indent=2))
    return run


def _discover_profile_suggestions(
    resume_text: str,
    existing_platforms: set[str],
) -> list[SourceEvidence]:
    if "github" in existing_platforms and "linkedin" in existing_platforms:
        return []
    try:
        hints = extract_identity_hints(resume_text)
    except (ValueError, LocalModelUnavailable):
        return []
    if not hints.full_name or len(_words(hints.full_name)) < 2:
        return []

    suggestions = _discover_exa_suggestions(hints, existing_platforms)
    try:
        query = urlencode(
            {
                "q": f"{hints.full_name} in:fullname",
                "per_page": 10,
            }
        )
        results = _get_json(f"https://api.github.com/search/users?{query}")
        if not isinstance(results, dict) or not isinstance(results.get("items"), list):
            results = {"items": [], "total_count": 0}
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        results = {"items": [], "total_count": 0}

    for item in results["items"]:
        if not isinstance(item, dict) or not item.get("url"):
            continue
        try:
            profile = _get_json(str(item["url"]))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            continue
        if not isinstance(profile, dict):
            continue
        signals = _suggestion_signals(
            _profile_match_signals(hints, profile)
        )
        if not signals:
            continue
        profile_url = str(profile.get("html_url") or "")
        if "github" not in existing_platforms and _platform_for_url(profile_url) == "github":
            suggestions.append(
                _identity_review_source("github", profile_url, signals)
            )
        blog_url = str(profile.get("blog") or "").strip()
        if blog_url and not blog_url.startswith(("http://", "https://")):
            blog_url = f"https://{blog_url}"
        if (
            "linkedin" not in existing_platforms
            and _platform_for_url(blog_url) == "linkedin"
        ):
            suggestions.append(
                _identity_review_source(
                    "linkedin",
                    blog_url.rstrip("/"),
                    signals + ["Linked from the corroborated GitHub profile"],
                )
            )
        if len(suggestions) >= 3:
            break
    best_by_platform: dict[str, SourceEvidence] = {}
    for suggestion in suggestions:
        current = best_by_platform.get(suggestion.platform)
        if current is None or len(suggestion.match_signals) > len(
            current.match_signals
        ):
            best_by_platform[suggestion.platform] = suggestion
    return list(best_by_platform.values())


def _discover_exa_suggestions(
    hints: IdentityHints,
    existing_platforms: set[str],
) -> list[SourceEvidence]:
    mcporter = shutil.which("mcporter")
    if not mcporter:
        return []
    qualifiers = (
        hints.locations[:1]
        + hints.employers[:1]
        + hints.roles[:1]
    )
    query = " ".join(
        [f'"{hints.full_name}"', *qualifiers, "LinkedIn GitHub professional profile"]
    )
    try:
        completed = subprocess.run(
            [
                mcporter,
                "call",
                "exa.web_search_exa",
                "--args",
                json.dumps({"query": query, "numResults": 8}),
                "--output",
                "json",
                "--timeout",
                "20000",
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=25,
        )
        payload = json.loads(completed.stdout)
        text = "\n".join(
            str(item.get("text") or "")
            for item in payload.get("content", [])
            if isinstance(item, dict) and item.get("type") == "text"
        )
    except (
        OSError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
        TypeError,
    ):
        return []

    suggestions: list[SourceEvidence] = []
    for block in text.split("\n---\n"):
        url_match = re.search(r"^URL:\s*(https?://\S+)", block, re.MULTILINE)
        if not url_match:
            continue
        result_url = url_match.group(1).rstrip(".,)")
        platform = _platform_for_url(result_url)
        candidate_url = result_url
        if platform is None:
            candidate_url = (
                _linkedin_profile_from_activity(result_url, hints.full_name) or ""
            )
            platform = _platform_for_url(candidate_url)
        if not platform or platform in existing_platforms:
            continue
        signals = _web_match_signals(hints, block)
        if len(signals) < 3:
            continue
        if candidate_url != result_url:
            signals.append(
                "A corroborated LinkedIn activity URL supplied the public profile handle"
            )
        suggestions.append(
            _identity_review_source(platform, candidate_url, signals)
        )
    return suggestions


def _linkedin_profile_from_activity(
    url: str,
    full_name: str | None = None,
) -> str | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    parts = parsed.path.strip("/").split("/")
    if host != "linkedin.com" or len(parts) < 2 or parts[0].lower() != "posts":
        return None
    author_slug = parts[1].split("_", 1)[0].strip("-")
    if not author_slug:
        return None
    if full_name:
        compact_slug = "".join(re.findall(r"[a-z]+", author_slug.lower()))
        name_parts = [
            part for part in re.findall(r"[a-z]+", full_name.lower()) if len(part) > 2
        ]
        if sum(part in compact_slug for part in name_parts) < 2:
            return None
    return f"https://linkedin.com/in/{author_slug}"


def _web_match_signals(hints: IdentityHints, text: str) -> list[str]:
    if not _words(hints.full_name or "").issubset(_words(text)):
        return []
    signals = ["Search result name matches the resume name"]
    if _overlaps(hints.locations, text):
        signals.append("Search result location matches a resume location")
    if _overlaps(hints.employers, text):
        signals.append("Search result employer matches a resume employer")
    if _overlaps(
        hints.roles,
        text,
        {
            "engineer",
            "developer",
            "software",
            "senior",
            "junior",
            "lead",
            "manager",
        },
    ):
        signals.append("Search result role matches a resume role")
    return signals


def _suggestion_signals(signals: list[str]) -> list[str]:
    if len(signals) >= 2:
        return signals
    return []


def _identity_review_source(
    platform: Literal["github", "linkedin"],
    url: str,
    signals: list[str],
) -> SourceEvidence:
    return SourceEvidence(
        platform=platform,
        url=url,
        retrieved_at=utc_now_iso(),
        status="needs_identity_review",
        identity_basis="unverified",
        match_signals=signals,
        error=(
            "Suggested public profile only. It is excluded from analysis and scoring "
            "until a person confirms the identity."
        ),
    )


def _words(value: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9]+", value.lower())
        if len(word) > 1
    }


def _overlaps(
    values: list[str],
    public_value: object,
    ignored: set[str] | None = None,
) -> bool:
    ignored = ignored or set()
    public_words = _words(str(public_value or "")) - ignored
    return any(
        bool((_words(value) - ignored) & public_words)
        for value in values
        if value.strip()
    )


def _profile_match_signals(
    hints: IdentityHints,
    profile: dict[str, object],
) -> list[str]:
    resume_name = _words(hints.full_name or "")
    public_name = _words(str(profile.get("name") or ""))
    shared_name = resume_name & public_name
    if (
        not resume_name
        or not public_name
        or len(shared_name) < 2
        or len(shared_name) / min(len(resume_name), len(public_name)) < 0.8
    ):
        return []

    signals = ["Public profile name matches the resume name"]
    if _overlaps(hints.locations, profile.get("location")):
        signals.append("Public profile location matches a resume location")
    if _overlaps(hints.employers, profile.get("company")):
        signals.append("Public profile employer matches a resume employer")
    if _overlaps(
        hints.roles,
        profile.get("bio"),
        {
            "engineer",
            "developer",
            "software",
            "senior",
            "junior",
            "lead",
            "manager",
        },
    ):
        signals.append("Public profile role matches a resume role")
    return signals


def _apply_shortlist(candidates: list[CandidateResearch]) -> int:
    scored = [
        candidate
        for candidate in candidates
        if candidate.fit_analysis.decision
        and candidate.fit_analysis.decision.evidence_score is not None
        and candidate.fit_analysis.decision.required_criteria_supported
        and candidate.fit_analysis.decision.fit_label
        != "insufficient_demonstrated_evidence"
    ]
    if not scored:
        return 0
    scored.sort(
        key=lambda candidate: (
            candidate.fit_analysis.decision.evidence_score,
            candidate.fit_analysis.decision.evidence_coverage,
        ),
        reverse=True,
    )
    target = min(len(scored), max(1, math.ceil(len(candidates) * 0.30)))
    cutoff = scored[target - 1].fit_analysis.decision.evidence_score
    selected = [
        candidate
        for candidate in scored
        if candidate.fit_analysis.decision.evidence_score >= cutoff
    ]
    for rank, candidate in enumerate(scored, start=1):
        decision = candidate.fit_analysis.decision
        decision.shortlist_rank = rank
        decision.top_30_percent = candidate in selected
    return len(selected)


def _add_confirmed_profiles(
    profiles: dict[str, tuple[str, str]],
    candidate: CandidateProfileInput,
) -> None:
    if candidate.github_url:
        url = str(candidate.github_url)
        _require_platform(url, "github")
        profiles["github"] = (url.rstrip("/"), "manager_confirmed")
    if candidate.linkedin_url:
        url = str(candidate.linkedin_url)
        _require_platform(url, "linkedin")
        profiles["linkedin"] = (url.rstrip("/"), "manager_confirmed")


def _platform_for_url(url: str) -> Literal["github", "linkedin"] | None:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    path = urlparse(url).path
    if host == "github.com" and len(path.strip("/").split("/")) == 1:
        return "github"
    if host == "linkedin.com" and path.lower().startswith("/in/"):
        return "linkedin"
    return None


def _require_platform(url: str, expected: Literal["github", "linkedin"]) -> None:
    if _platform_for_url(url) != expected:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"URL is not a valid {expected} profile URL: {url}",
        )


def _research_source(
    platform: Literal["github", "linkedin"],
    url: str,
    basis: Literal["resume_link", "manager_confirmed"],
    job_description: str,
) -> SourceEvidence:
    try:
        if platform == "github":
            excerpt = _read_github_profile(url)
        else:
            excerpt = _read_linkedin_profile(url, job_description)
        if not excerpt:
            raise ValueError("No job-relevant public evidence was returned.")
        return SourceEvidence(
            platform=platform,
            url=url,
            retrieved_at=utc_now_iso(),
            content_hash=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
            status="verified",
            identity_basis=basis,
            job_relevant_excerpt=excerpt,
        )
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        return SourceEvidence(
            platform=platform,
            url=url,
            retrieved_at=utc_now_iso(),
            status="unavailable",
            identity_basis=basis,
            error=str(exc),
        )


def _get_json(url: str) -> object:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urlopen(request, timeout=WEB_REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _read_github_profile(profile_url: str) -> str:
    username = urlparse(profile_url).path.strip("/").split("/")[0]
    profile = _get_json(f"https://api.github.com/users/{username}")
    repos = _get_json(
        f"https://api.github.com/users/{username}/repos"
        "?sort=updated&direction=desc&per_page=20&type=owner"
    )
    if not isinstance(profile, dict) or not isinstance(repos, list):
        raise ValueError("GitHub returned an unexpected response.")

    # Deliberately omit followers, stars, avatar, location, and other popularity or
    # potentially sensitive fields. Only work-product evidence is retained.
    lines = [
        f"GitHub account: {profile.get('html_url', profile_url)}",
        f"Account name: {profile.get('name') or username}",
        "Recent public repositories:",
    ]
    for repo in repos:
        if not isinstance(repo, dict) or repo.get("fork"):
            continue
        description = str(repo.get("description") or "No description").strip()
        language = str(repo.get("language") or "unspecified")
        lines.append(
            f"- {repo.get('name', 'unnamed')} | language: {language} | {description}"
        )
    return "\n".join(lines)


def _read_linkedin_profile(profile_url: str, job_description: str) -> str:
    # This is Agent-Reach's zero-configuration LinkedIn fallback: Jina Reader
    # reads a candidate-provided public profile without browser credentials.
    reader_url = f"https://r.jina.ai/{profile_url}"
    request = Request(reader_url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=WEB_REQUEST_TIMEOUT_SECONDS) as response:
        page_text = response.read().decode("utf-8", errors="replace")
    try:
        return sanitize_linkedin_evidence(page_text, job_description)
    except LocalModelUnavailable as exc:
        # Do not persist an unfiltered LinkedIn page when local sensitive-data
        # filtering cannot run.
        raise ValueError(str(exc)) from exc
