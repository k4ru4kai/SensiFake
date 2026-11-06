# Candidate-only privacy patch

The targeted review classified the ten previously withheld CSVs as three LOW
and seven REVIEW, with no confirmed HIGH findings. They are not presumed private
merely because they contain research annotations or contributor labels.

The three LOW files are restored byte-for-byte: the aggregate development
summary, blinded reannotation subset and gold/silver split assignment. The seven
REVIEW files are public derivatives. The patch:

- Uses stable rater codes in assignment fields and matching neutral task filenames.
  Task-file bodies are byte-identical. All image membership, order, split seeds
  and rater-group relationships are retained.
- Replaces the attribution token embedded in batch IDs bijectively, retaining
  batch membership and uniqueness. It does not reseed or regenerate assignments.
- Blanks six optional rationales, keeping their schema column. Exact operational
  annotation/adjudication times are rounded to the start of the original calendar
  day, retaining date and timezone; these values do not claim exact observation
  times. Retaining valid ISO timestamps keeps the existing annotation reader usable.
- Uses a stable actor code for populated adjudicator fields and aliases only
  person-labelled relative source-path components. Source partitions, asset
  filenames, ordered path multiplicity, image hashes, labels, decisions and
  probabilities remain intact. Path aliases are provenance locators; they do
  not create local images. Resolve published images by content identity.

`privacy_patch_manifest.json` records source commit/content digests, candidate
digests, changed columns/counts, and fingerprints of unchanged scientific
columns in original row order. It contains no explicit identity-to-code mapping.
The private audit records exact source/destination paths and independent
comparisons, without copying rationales or raw attribution/timestamp values.
The immutable published Git versions and separate original repositories remain
unchanged. These files are not described as byte-identical where cells changed.

This is **pseudonymization and data minimization, not full anonymity**. Public
Git history and stable image identities still permit linkage; original content
digests also preserve research traceability. Name-bearing source paths in other
historical files and source-code examples remain outside this ten-file patch.
The patch does not remove contributor credits, citations, authorship records or
scientific provenance. Appropriate contributor attribution remains welcome;
consent for republishing individual attribution and optional free text is still
unconfirmed. No history rewrite is warranted by this patch alone.

This local patch is prepared for review only. No commit, push, pull request,
GitHub or Hugging Face modification was performed or authorized.
