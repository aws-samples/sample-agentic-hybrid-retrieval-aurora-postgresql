/**
 * The commands a participant types, as the lab guides print them.
 *
 * The UI cannot import `service/participant_commands.py`, so these are its
 * copies. tests/test_participant_commands.py fails when any of them drifts
 * from the Python source.
 */
export const APPLY_SQL = "uv run python scripts/apply_search_functions.py";
export const DEPLOY_AGENT = "uv run python scripts/deploy_agentcore.py deploy";
export const VERIFY_AGENT = "uv run python scripts/deploy_agentcore.py verify";

export function validateCommand(lab: number): string {
  return `uv run python scripts/validate_lab.py --lab ${lab}`;
}
