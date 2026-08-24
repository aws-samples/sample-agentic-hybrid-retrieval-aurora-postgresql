# Payment marks

The storefront footer shows a row of payment plates. Until official artwork lands
here, those plates carry generic marks from the icon set the rest of the UI uses
(`Credit and debit`, `Contactless`, `Digital wallet`, `Bank transfer`), which name
payment families rather than networks.

Card network marks are trademarks, licensed to merchants who accept that card.
This catalog accepts nothing, so the marks cannot be added on the strength of the
footer looking better with them: each one needs artwork obtained from its owner's
brand programme and a note recording that permission, the same way
`../GITHUB-MARK-LICENSE.txt` records GitHub's MIT terms for `../github-mark.svg`.

## What to add

One SVG per mark, plus one note per mark, named for the `id` used in
`ui/src/components/SiteFooter.tsx`:

| File            | Mark        | Source                                    |
| --------------- | ----------- | ----------------------------------------- |
| `visa.svg`      | Visa        | Visa brand centre                         |
| `mastercard.svg`| Mastercard  | Mastercard brand centre                   |
| `amex.svg`      | American Express | American Express brand and merchant assets |
| `paypal.svg`    | PayPal      | PayPal logo and brand guidelines          |
| `apple-pay.svg` | Apple Pay   | Apple Pay marketing guidelines            |
| `google-pay.svg`| Google Pay  | Google Pay brand guidelines               |

Take only the marks the footer should show. The row is not a fixed set of six.

Each SVG needs a sibling `<NAME>-LICENSE.txt` naming the mark, the source URL it
was downloaded from, the owner, and the permission or licence it is used under.
The pattern to copy is `../GITHUB-MARK-LICENSE.txt`.

## Artwork requirements

- Keep the network's own colour artwork. The plate behind it is white, so
  monochrome variants disappear into it.
- Trim the SVG to the mark, with no built-in white card or padding. The plate
  supplies both, and a mark with its own background sits on a second one.
- Set a `viewBox` and no fixed `width`/`height`, so the CSS can size the row
  consistently across marks of different proportions.
- No raster fallbacks. Every mark in the row scales with the page.

## Wiring them up

Replace the entries in `paymentMarks` in `ui/src/components/SiteFooter.tsx`. The
`art` field takes the element, so an entry becomes an `img` with an empty `alt`
and `aria-hidden`, pointed at `/assets/icons/payment/<id>.svg`, with the `label`
carrying the accessible name.

Two guards will hold you to it:

- `ui/src/assetReferences.test.ts` fails if a referenced path is missing from
  `public/` or is present but untracked by git. Local-only files are the failure
  mode it exists for: the footer looks right here and ships empty for everyone
  who clones.
- `ui/src/components/Shell.test.tsx` asserts the footer names no card network.
  It is deliberate, and it is the record that the generic marks were a decision
  rather than an oversight. Update that assertion in the same commit that adds
  the artwork and the permission notes, so the reason for the change is in one
  place.
