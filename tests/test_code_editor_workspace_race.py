"""Code Editor's first load of the multi-root workspace must not stall on its race."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "deploy/mosaic-bootstrap.sh"
SPEC = importlib.util.spec_from_file_location(
    "patch_code_editor_workspace_race",
    ROOT / "deploy/patch_code_editor_workspace_race.py",
)
race = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(race)

# The two sites as Code Editor 1.101.2 ships them in
# out/vs/code/browser/workbench/workbench.js.
HANDLER = (
    "this.z=this.B(new KYs(e,r,a,l)),this.B(this.z.onDidUpdateConfiguration(h=>{this.yb(h)"
    ".then(()=>{this.c.initialized=this.z.initialized,this.gb(h)})})),this.B(this.r.onDid"
)
INITIALIZE = (
    'async initialize(i){Ni("code/willInitWorkspaceService");const e=this.n;this.n=!1;'
    "const t=await this.cb(i);await this.hb(t,e),this.gb(!1),"
    'Ni("code/didInitWorkspaceService")}updateWorkspaceTrust(i){'
)
BUNDLE = "/*head*/" + HANDLER + "/*middle*/" + INITIALIZE + "/*tail*/"


def test_a_stalled_first_load_completes_once_the_workspace_file_has_loaded():
    """On a test event 6 of 10 fresh loads kept the Explorer's clock and no terminal.

    The handler threw before the workspace existed, and initialize() kept the stale
    value; patched, 0 of 20 loads stalled.
    """
    patched, outcome = race.patch(BUNDLE)
    assert outcome == "patched"
    assert (
        "then(()=>{this.c&&(this.c.initialized=this.z.initialized,this.gb(h))})"
        in patched
    )
    assert (
        "await this.hb(t,e),this.c.initialized=this.c.initialized||this.z.initialized"
        '/*mosaic-workspace-race*/,this.gb(!1),Ni("code/didInitWorkspaceService")'
        in patched
    )
    assert patched.startswith("/*head*/") and patched.endswith("/*tail*/")


def test_a_second_run_changes_nothing():
    patched, _ = race.patch(BUNDLE)
    assert race.patch(patched) == (patched, "already patched")


def test_a_build_it_does_not_recognise_is_left_untouched():
    """A build that renames or fixes either site stays as shipped, never half-patched."""
    renamed = BUNDLE.replace("this.gb(!1)", "this.kb(!1)")
    fixed = BUNDLE.replace(HANDLER, "")
    for bundle in (renamed, fixed):
        unchanged, outcome = race.patch(bundle)
        assert unchanged == bundle
        assert outcome.startswith("unrecognised")


def test_the_cli_writes_the_patch_and_reports_each_file(tmp_path, capsys, monkeypatch):
    workbench = tmp_path / "workbench.js"
    workbench.write_text(BUNDLE)
    monkeypatch.setattr("sys.argv", ["patch", str(workbench)])
    race.main()
    assert race.MARK in workbench.read_text()
    assert capsys.readouterr().out == f"{workbench}: patched\n"


def test_bootstrap_patches_the_editor_before_a_participant_loads_it():
    """The checkout supplies the script, and the restart serves the patched copy."""
    script = BOOTSTRAP.read_text()
    checkout = script.index('git -C "$REPO" checkout --detach FETCH_HEAD')
    patch_at = script.index('"$REPO/deploy/patch_code_editor_workspace_race.py"')
    restart = script.index("systemctl restart code-editor", patch_at)
    complete = script.index("MOSAIC_BOOTSTRAP_COMPLETE")
    assert checkout < patch_at < restart < complete
    assert 'sudo -u "$CODE_EDITOR_USER" python3.13' in script[patch_at - 120 : patch_at]
    assert (
        'CODE_EDITOR_WORKBENCH="$CODE_EDITOR_ROOT/dist/out/vs/code/browser/workbench/'
        'workbench.js"' in script
    )
