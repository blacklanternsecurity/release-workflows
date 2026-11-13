"""The exemption step of cla-reusable.yml, run with a stub `gh` in place of the GitHub API.

Signing means the CLA sign-phrase comment; commit signatures play no part. On a pull request opened by an
org member or a named bot, other members and named bots are exempt. On one opened by anyone else, the
opener and every commit author must sign, members included: a commit's author is only an email, so there
no author can be trusted to be a member.
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).parent.parent / ".github" / "workflows" / "cla-reusable.yml"
STEP = next(s for s in yaml.safe_load(WORKFLOW.read_text())["jobs"]["CLAAssistant"]["steps"] if s.get("id") == "cla-check")["run"]

GH_STUB = """#!/bin/bash
case "$2" in
  orgs/blacklanternsecurity/members/*)
    [ "$MEMBERS" = FAIL ] && exit 1
    case " $MEMBERS " in *" ${2##*/} "*) exit 0 ;; esac
    exit 1 ;;
  repos/o/r/pulls/7) printf '{"user":{"login":"%s"},"commits":%s}\\n' "$OPENER" "$N_COMMITS" ;;
  repos/o/r/pulls/7/commits*) [ -n "$COMMITS_FAIL" ] && { echo "HTTP 502" >&2; exit 1; }; cat "$COMMITS_FILE" ;;
  *) echo "unexpected: gh $*" >&2; exit 2 ;;
esac
"""


def run_step(tmp_path, opener, members, commits, n_commits=None, commits_fail=False):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(GH_STUB)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    commits_file = tmp_path / "commits.tsv"
    commits_file.write_text("".join(c + "\n" for c in commits))
    output = tmp_path / "out"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(output),
        "REPO": "o/r",
        "PR_NUM": "7",
        "GH_TOKEN": "app",
        "PR_TOKEN": "pr",
        "OPENER": opener,
        "MEMBERS": members,
        "N_COMMITS": str(len(commits) if n_commits is None else n_commits),
        "COMMITS_FILE": str(commits_file),
        "COMMITS_FAIL": "1" if commits_fail else "",
    }
    result = subprocess.run(["bash", "-c", STEP], cwd=tmp_path, env=env, capture_output=True, text=True)
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines()) if output.exists() else {}
    required = sorted(line.removesuffix(": CLA required") for line in result.stdout.splitlines() if line.endswith(": CLA required"))
    return result, outputs, required


CASES = [
    # (name, opener, members, commit authors, all_exempt, allowlist, required)
    ("member opens PR with own commits: exempt", "m1", "m1", ["m1"], "true", "m1", []),
    ("member commits on another member's PR: exempt", "m1", "m1 m2", ["m1", "m2"], "true", "m1,m2", []),
    ("member PR with dependabot commit: exempt", "m1", "m1", ["m1", "dependabot[bot]"], "true", "dependabot[bot],m1", []),
    ("dependabot PR: exempt", "dependabot[bot]", "m1", ["dependabot[bot]"], "true", "dependabot[bot]", []),
    ("external commit on a member's PR: external signs", "m1", "m1", ["m1", "ext"], "false", "m1", ["ext"]),
    ("external opens PR with own commits: external signs", "ext", "m1", ["ext"], "false", "", ["ext"]),
    ("another external's commit on an external's PR: both sign", "ext", "m1", ["ext", "ext2"], "false", "", ["ext", "ext2"]),
    ("member commit on an external's PR: member signs too", "ext", "m1", ["ext", "m1"], "false", "", ["ext", "m1"]),
    ("external's PR with a commit claiming dependabot: must sign", "ext", "m1", ["ext", "dependabot[bot]"], "false", "", ["dependabot[bot]", "ext"]),
    ("membership lookup fails: not a member", "m1", "FAIL", ["m1"], "false", "", ["m1"]),
]


@pytest.mark.parametrize("name,opener,members,commits,all_exempt,allowlist,required", CASES, ids=[c[0] for c in CASES])
def test_exemption(tmp_path, name, opener, members, commits, all_exempt, allowlist, required):
    result, outputs, got_required = run_step(tmp_path, opener, members, commits)
    assert result.returncode == 0, result.stdout + result.stderr
    assert outputs == {"all_exempt": all_exempt, "allowlist": allowlist}
    assert got_required == required


def test_more_than_100_commits_fails(tmp_path):
    result, outputs, _ = run_step(tmp_path, "m1", "m1", ["m1"], n_commits=346)
    assert result.returncode != 0
    assert "only the first 100" in result.stdout
    assert outputs == {}


def test_bracketed_login_is_not_a_glob(tmp_path):
    (tmp_path / "dependabotb").write_text("")
    _, outputs, required = run_step(tmp_path, "ext", "m1", ["ext", "dependabot[bot]"])
    assert required == ["dependabot[bot]", "ext"]
    assert outputs["allowlist"] == ""


def test_external_opener_without_a_commit_fails(tmp_path):
    result, outputs, _ = run_step(tmp_path, "ext", "m1", ["m1"])
    assert result.returncode != 0
    assert "The opener (ext) must sign the CLA" in result.stdout
    assert outputs == {}


@pytest.mark.parametrize("commits", [["null"], ["null", "m1"], ["m1", "null"], ["ext", "null"]], ids=str)
@pytest.mark.parametrize("opener", ["m1", "ext"])
def test_commit_without_a_github_login_fails(tmp_path, opener, commits):
    # The action would credit the commit to its committer, who may be allowlisted or may have signed.
    result, outputs, _ = run_step(tmp_path, opener, "m1", commits)
    assert result.returncode != 0
    assert "not linked to a GitHub account" in result.stdout
    assert outputs == {}


def test_failed_commits_read_fails(tmp_path):
    result, outputs, _ = run_step(tmp_path, "m1", "m1", ["m1"], commits_fail=True)
    assert result.returncode != 0
    assert outputs == {}


def test_commit_count_mismatch_fails(tmp_path):
    result, outputs, _ = run_step(tmp_path, "m1", "m1", ["m1"], n_commits=2)
    assert result.returncode != 0
    assert "Read 1 commit authors, but this pull request has 2 commits" in result.stdout
    assert outputs == {}


def test_empty_commit_list_fails(tmp_path):
    result, outputs, _ = run_step(tmp_path, "m1", "m1", [], n_commits=1)
    assert result.returncode != 0
    assert "Read 0 commit authors" in result.stdout
    assert outputs == {}


@pytest.mark.parametrize("n_commits", ["null", "0"])
def test_unreadable_commit_count_fails(tmp_path, n_commits):
    result, outputs, _ = run_step(tmp_path, "m1", "m1", ["m1"], n_commits=n_commits)
    assert result.returncode != 0
    assert "Could not read this pull request's commit count" in result.stdout
    assert outputs == {}
