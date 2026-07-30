// The persona vocabulary, in one place (A7: one identity axis). Pure data and
// pure functions — no React, no fetch — so route.ts, the app, and the G-23 gate
// harness can all import it without pulling in the component tree.
//
// These three values are the SAME enum as backend/app/models.py's Persona and
// backend/app/db.py's PERSONAS. A fourth value here without the matching
// GRANT in sql/11_roles_rls.sql produces a request that fails with
// `permission denied to set role`, which is the correct failure: the database
// is the authority on which identities exist.

export type PersonaKey = 'analyst' | 'admin' | 'auditor';

export const PERSONA_KEYS: readonly PersonaKey[] = [
  'analyst',
  'admin',
  'auditor',
];

export const DEFAULT_PERSONA: PersonaKey = 'analyst';

// Chip copy (A4). "Viewing as" is the frame; these are the values inside it.
// Never "Sign in as" — the chip mirrors the identity the request carried, it
// does not grant one.
export const PERSONA_LABELS: Record<PersonaKey, string> = {
  analyst: 'Analyst',
  admin: 'Admin',
  auditor: 'Auditor',
};

// What the app asked Postgres to become. Rendered in the receipt so a
// participant can paste the same statement into psql and see the same rows.
export const PERSONA_DB_ROLES: Record<PersonaKey, string> = {
  analyst: 'persona_analyst',
  admin: 'persona_admin',
  auditor: 'persona_auditor',
};

export function isPersonaKey(value: string): value is PersonaKey {
  return (PERSONA_KEYS as string[]).includes(value);
}

export function personaLabel(value?: string): string {
  return value && isPersonaKey(value)
    ? PERSONA_LABELS[value]
    : PERSONA_LABELS[DEFAULT_PERSONA];
}

/**
 * The one statement the app issued for this persona. Rendered verbatim in the
 * flip receipt: the app's claim about what it did must be the pasteable proof
 * of what it did.
 */
export function personaSetRoleSql(value: PersonaKey): string {
  return `SET LOCAL ROLE ${PERSONA_DB_ROLES[value]};`;
}
