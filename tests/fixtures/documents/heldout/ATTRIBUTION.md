# Held-out benchmark documents — sources and licence

These four French-language texts are **external**: nobody on this project wrote
them. That is the only property which makes the held-out benchmark score mean
anything. See `declaw/documents/corpus/heldout.py` for the two rules that govern
their use.

## Source

All four come from the EU Publications Office's CELLAR content repository, the
machine-facing endpoint behind EUR-Lex:

```
http://publications.europa.eu/resource/celex/{CELEX}.FRA
Accept: application/xhtml+xml
```

During the 2026-08-26 collection session, the tested EUR-Lex page requests
returned a JavaScript cookie-consent interstitial rather than document text.
CELLAR was used instead. This records that retrieval environment, not a current
claim about every EUR-Lex URL or client.

**Retrieved:** 2026-08-26.

| File | CELEX | Title |
| --- | --- | --- |
| `rgpd-2016-679.txt` | 32016R0679 | Règlement (UE) 2016/679 — protection des données (RGPD) |
| `directive-2019-790-droit-auteur.txt` | 32019L0790 | Directive (UE) 2019/790 — droit d'auteur dans le marché unique numérique |
| `directive-2011-83-consommateurs.txt` | 32011L0083 | Directive 2011/83/UE — droits des consommateurs |
| `directive-2014-24-marches-publics.txt` | 32014L0024 | Directive 2014/24/UE — passation des marchés publics |

Canonical EUR-Lex page for any of them:
`https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:{CELEX}`

## What was changed

The originals are XHTML. Markup was stripped to plain text — tags removed,
HTML entities unescaped, paragraph breaks preserved — because DeClaw's parsers
read `.txt` directly and committing ~3 MB of markup would serve no purpose.

**No document was excerpted, reordered, or edited.** Each file holds its
complete text. Excerpting would have meant choosing which passages survive,
which is precisely the bias a held-out set exists to avoid.

The session-local conversion script was named `scratchpad/fetch_heldout.py`;
it is not committed in this repository. The source identifiers and conversion
description above support recreating an extractor, but the original conversion
cannot be rerun from a checked-in script. Preserve these committed fixtures and
verify benchmark snippets against them rather than assuming a fresh download is
byte-identical.

## Licence and reuse

EUR-Lex content is reusable under the European Commission's reuse policy
(Decision 2011/833/EU): reproduction is authorised provided the source is
acknowledged, which this file does. The Publications Office notes that only the
Official Journal of the European Union in its printed or authenticated
electronic form is authentic; these copies are for testing DeClaw's retrieval
and carry no legal authority.

© European Union, 1998-2026 — https://eur-lex.europa.eu
