"""The exemption step of cla-reusable.yml, run with a stub `gh` in place of the GitHub API.

A commit's author is only an email, so a commit can claim to be from a member or a bot. These cases check
that such a claim exempts nobody unless the pull request's opener (verified by GitHub) is a member or a
named bot, or the commit is signed and committed by that same member.
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
  repos/o/r/pulls/7/commits*) cat "$COMMITS_FILE" ;;
  *) echo "unexpected: gh $*" >&2; exit 2 ;;
esac
"""


def run_step(tmp_path, opener, members, commits, n_commits=None):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(GH_STUB)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    commits_file = tmp_path / "commits.tsv"
    commits_file.write_text("".join("\t".join(c) + "\n" for c in commits))
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
    }
    result = subprocess.run(["bash", "-c", STEP], cwd=tmp_path, env=env, capture_output=True, text=True)
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines()) if output.exists() else {}
    required = sorted(
        line.removesuffix(": CLA required") for line in result.stdout.splitlines() if line.endswith(": CLA required") and "no GitHub login" not in line
    )
    return result, outputs, required


SIGNED, UNSIGNED = "true", "false"

CASES = [
    # (name, opener, members, commits [(author, committer, verified)], all_exempt, allowlist, required)
    ("outsider PR, own commits", "out", "m1 m2", [("out", "out", UNSIGNED)], "false", "", ["out"]),
    ("outsider PR, commit claims a member's email", "out", "m1", [("out", "out", UNSIGNED), ("m1", "out", UNSIGNED)], "false", "", ["m1", "out"]),
    ("outsider PR, unsigned commit claims member as author and committer", "out", "m1", [("m1", "m1", UNSIGNED)], "false", "", ["m1"]),
    ("outsider PR, commit claims dependabot", "out", "m1", [("dependabot[bot]", "dependabot[bot]", SIGNED)], "false", "", ["dependabot[bot]"]),
    ("outsider PR, member's signed commit plus own", "out", "m1", [("m1", "m1", SIGNED), ("out", "out", UNSIGNED)], "false", "m1", ["out"]),
    ("outsider PR, member's signed commit plus one claiming the member", "out", "m1", [("m1", "m1", SIGNED), ("m1", "out", UNSIGNED)], "false", "", ["m1"]),
    ("outsider PR, outsider-signed commit authored as member", "out", "m1", [("m1", "out", SIGNED)], "false", "", ["m1"]),
    (
        "member PR, member and dependabot commits",
        "m1",
        "m1 m2",
        [("m2", "m2", UNSIGNED), ("dependabot[bot]", "web-flow", SIGNED)],
        "true",
        "dependabot[bot],m2",
        [],
    ),
    ("member PR, outsider commit", "m1", "m1", [("m1", "m1", UNSIGNED), ("out", "out", UNSIGNED)], "false", "m1", ["out"]),
    ("dependabot PR", "dependabot[bot]", "m1", [("dependabot[bot]", "web-flow", SIGNED)], "true", "dependabot[bot]", []),
    ("member PR, commit without a GitHub login", "m1", "m1", [("null", "null", UNSIGNED)], "false", "", ["<none>"]),
    ("membership lookup fails: not exempt", "m1", "FAIL", [("m1", "m1", SIGNED)], "false", "", ["m1"]),
]


@pytest.mark.parametrize("name,opener,members,commits,all_exempt,allowlist,required", CASES, ids=[c[0] for c in CASES])
def test_exemption(tmp_path, name, opener, members, commits, all_exempt, allowlist, required):
    result, outputs, got_required = run_step(tmp_path, opener, members, commits)
    assert result.returncode == 0, result.stdout + result.stderr
    assert outputs == {"all_exempt": all_exempt, "allowlist": allowlist}
    assert got_required == required


def test_more_than_100_commits_fails(tmp_path):
    result, outputs, _ = run_step(tmp_path, "m1", "m1", [("m1", "m1", SIGNED)], n_commits=346)
    assert result.returncode != 0
    assert "only the first 100" in result.stdout
    assert outputs == {}


def test_bracketed_login_is_not_a_glob(tmp_path):
    (tmp_path / "dependabotb").write_text("")
    _, outputs, required = run_step(tmp_path, "out", "m1", [("dependabot[bot]", "x", UNSIGNED)])
    assert required == ["dependabot[bot]"]
    assert outputs["allowlist"] == ""
