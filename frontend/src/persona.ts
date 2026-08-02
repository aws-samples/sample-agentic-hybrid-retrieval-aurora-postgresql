// The persona vocabulary, in one place (A7: one identity axis). Pure data and
// pure functions — no React, no fetch — so route.ts, the app, and the G-23 gate
// harness can all import it without pulling in the component tree.
//
// These three values are the SAME enum as backend/app/models.py's Persona and
// backend/app/db.py's PERSONAS. They remain receipt metadata for production
// extension; the live workshop uses the fixed core visibility scope.

export type PersonaKey = 'app_engineer' | 'auditor' | 'dba';

export const PERSONA_KEYS: readonly PersonaKey[] = [
  'app_engineer',
  'auditor',
  'dba',
];

export const DEFAULT_PERSONA: PersonaKey = 'app_engineer';

// Chip copy (A4). "Viewing as" is the frame; these are the values inside it.
// Never "Sign in as" — the chip mirrors the identity the request carried, it
// does not grant one.
export const PERSONA_LABELS: Record<PersonaKey, string> = {
  app_engineer: 'App Engineer',
  dba: 'DBA',
  auditor: 'Auditor',
};

export function isPersonaKey(value: string): value is PersonaKey {
  return (PERSONA_KEYS as string[]).includes(value);
}

export function personaLabel(value?: string): string {
  return value && isPersonaKey(value)
    ? PERSONA_LABELS[value]
    : PERSONA_LABELS[DEFAULT_PERSONA];
}
