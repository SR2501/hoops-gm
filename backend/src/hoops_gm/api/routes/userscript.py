"""Userscript delivery and version status for Tampermonkey.

Mounted unversioned, like ``/health``: this is a static-file surface, not a
JSON API contract, and Tampermonkey's update URL must stay stable regardless
of ``/api/v1`` evolving. Loopback-only (ADR-001) and, per ADR-010, never
serves anything containing a secret — the userscript obtains its bearer
secret only through the pairing handshake, never a build artifact, so these
bytes are safe to serve to any local caller that can already reach this port.

``package.json`` owns the source version. The delivery route parses
``@version`` from the exact bytes it would return and refuses disagreement;
the adjacent status route adds the installed ``GM_info`` version for the
Fantrax status strip. Neither route authenticates or performs an account
action: this boundary describes local build currency only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal, NoReturn

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel

from hoops_gm.api.security import require_loopback_host

router = APIRouter(tags=["userscript"])

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
_ARTIFACT_VERSION = re.compile(rb"^// @version[ \t]+(\S+)[ \t]*$", re.MULTILINE)
_METADATA_BLOCK = re.compile(
    rb"\A// ==UserScript==\r?\n(?P<body>.*?)^// ==/UserScript==\r?(?:\n|\Z)",
    re.MULTILINE | re.DOTALL,
)
_BUILD_MISSING_DETAIL = (
    "The userscript build is missing. From the userscript/ directory, run "
    "`npm install` once and then `npm run build` to produce "
    "dist/hoops-gm.user.js, then reload this URL."
)
_BUILD_UNREADABLE_DETAIL = "The userscript build exists but could not be read."
_SOURCE_UNREADABLE_DETAIL = "The userscript source version could not be read from package.json."
_ARTIFACT_VERSION_DETAIL = "The userscript build has no single valid @version metadata value."
_VERSION_MISMATCH_DETAIL = (
    "The userscript build does not match the repository source version. From the "
    "userscript/ directory, run `npm run build`, then retry."
)


class UserscriptVersionStatus(BaseModel):
    """Repository, served-artifact, and installed-script version agreement."""

    status: Literal["current", "update_available", "mismatch", "uncheckable"]
    installed_version: str | None
    source_version: str | None
    served_version: str | None
    reason: str | None


class UserscriptBuildProblem(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        error: str,
        detail: str,
        source_version: str | None = None,
        served_version: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.error = error
        self.detail = detail
        self.source_version = source_version
        self.served_version = served_version


def _read_source_version(path: Path) -> str:
    try:
        package = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UserscriptBuildProblem(
            status_code=500,
            error="userscript_source_version_uncheckable",
            detail=_SOURCE_UNREADABLE_DETAIL,
        ) from exc
    version = package.get("version") if isinstance(package, dict) else None
    if not isinstance(version, str) or _SEMVER.fullmatch(version) is None:
        raise UserscriptBuildProblem(
            status_code=500,
            error="userscript_source_version_uncheckable",
            detail=_SOURCE_UNREADABLE_DETAIL,
        )
    return version


def _read_built_userscript(path: Path, source_version: str) -> tuple[bytes, str]:
    try:
        content = path.read_bytes()
    except FileNotFoundError as exc:
        raise UserscriptBuildProblem(
            status_code=404,
            error="userscript_build_missing",
            detail=_BUILD_MISSING_DETAIL,
            source_version=source_version,
        ) from exc
    except OSError as exc:
        raise UserscriptBuildProblem(
            status_code=500,
            error="userscript_build_unreadable",
            detail=_BUILD_UNREADABLE_DETAIL,
            source_version=source_version,
        ) from exc

    metadata_match = _METADATA_BLOCK.match(content)
    metadata = metadata_match.group("body") if metadata_match else b""
    matches = _ARTIFACT_VERSION.findall(metadata)
    try:
        served_version = matches[0].decode("ascii") if len(matches) == 1 else None
    except UnicodeDecodeError:
        served_version = None
    if served_version is None or _SEMVER.fullmatch(served_version) is None:
        raise UserscriptBuildProblem(
            status_code=500,
            error="userscript_build_version_uncheckable",
            detail=_ARTIFACT_VERSION_DETAIL,
            source_version=source_version,
        )
    return content, served_version


def _load_current_userscript(request: Request) -> tuple[bytes, str]:
    settings = request.app.state.settings
    source_version = _read_source_version(settings.userscript_package_path)
    content, served_version = _read_built_userscript(settings.userscript_dist_path, source_version)
    if served_version != source_version:
        raise UserscriptBuildProblem(
            status_code=409,
            error="userscript_build_version_mismatch",
            detail=_VERSION_MISMATCH_DETAIL,
            source_version=source_version,
            served_version=served_version,
        )
    return content, source_version


def _raise_http(problem: UserscriptBuildProblem) -> NoReturn:
    raise HTTPException(
        status_code=problem.status_code,
        detail=problem.detail,
        headers={"X-Bridge-Error": problem.error},
    )


@router.get(
    "/bridge/userscript.user.js",
    summary="Serve the built userscript (install + @updateURL/@downloadURL target)",
)
def get_userscript(request: Request) -> Response:
    require_loopback_host(
        request,
        error_code="userscript_local_only",
        detail="The userscript is only served to the local machine.",
    )
    try:
        content, version = _load_current_userscript(request)
    except UserscriptBuildProblem as problem:
        _raise_http(problem)

    return Response(
        content=content,
        media_type="text/javascript; charset=utf-8",
        # Tampermonkey's own update check already avoids the browser HTTP
        # cache, but an intermediate cache remembering a stale build would
        # quietly defeat auto-update entirely, so this is explicit rather
        # than left to the default.
        headers={
            "Cache-Control": "no-store",
            "X-Hoops-GM-Userscript-Version": version,
        },
    )


@router.get(
    "/bridge/userscript-status.json",
    response_model=UserscriptVersionStatus,
    summary="Compare repository, served, and installed userscript versions",
)
def get_userscript_status(
    request: Request,
    response: Response,
    installed_version: str | None = Query(default=None),
) -> UserscriptVersionStatus:
    require_loopback_host(
        request,
        error_code="userscript_local_only",
        detail="The userscript status is only served to the local machine.",
    )
    response.headers["Cache-Control"] = "no-store"

    try:
        _content, source_version = _load_current_userscript(request)
    except UserscriptBuildProblem as problem:
        return UserscriptVersionStatus(
            status="mismatch"
            if problem.error == "userscript_build_version_mismatch"
            else "uncheckable",
            installed_version=installed_version
            if isinstance(installed_version, str) and _SEMVER.fullmatch(installed_version)
            else None,
            source_version=problem.source_version,
            served_version=problem.served_version,
            reason=problem.error,
        )

    if installed_version is None or _SEMVER.fullmatch(installed_version) is None:
        return UserscriptVersionStatus(
            status="uncheckable",
            installed_version=None,
            source_version=source_version,
            served_version=source_version,
            reason="installed_version_uncheckable",
        )

    installed_parts = tuple(int(part) for part in installed_version.split("."))
    source_parts = tuple(int(part) for part in source_version.split("."))
    if installed_parts == source_parts:
        status: Literal["current", "update_available", "mismatch"] = "current"
        reason = None
    elif installed_parts < source_parts:
        status = "update_available"
        reason = "installed_version_behind"
    else:
        status = "mismatch"
        reason = "installed_version_ahead"
    return UserscriptVersionStatus(
        status=status,
        installed_version=installed_version,
        source_version=source_version,
        served_version=source_version,
        reason=reason,
    )
