# License and attribution review — proposals only

No new license is applied. Possession of code, dataset publication or a Git
author field is not proof of ownership or permission. This review separates
code, annotations/database contributions, third-party image content and weights.
Existing notices/history are preserved; no Hugging Face content was changed.

## v0.1 distribution scope

The practical research release retains existing public code and notices, newly
commissioned access/verification tools, privacy-minimized metadata and saved
experimental results. Nineteen newly imported source files with unestablished
publication permission are excluded; see [DEFERRED_SOURCE.md](DEFERRED_SOURCE.md).
The image/weight licensing questions below remain limitations of those external
materials; neither images nor weights are redistributed here. No proposal below
is a license grant or a prerequisite for publishing unrelated cleared components.

## Source/revision/subset matrix

| Layer/source | Subset / count | Revision evidence | Terms observed | Release decision |
| --- | --- | --- | --- | --- |
| Original SensiFake code | existing remote + local contributors | 4c0f2749e839c84397b73f0ef4bb848471842af5 | No root code LICENSE in inspected main | UNRESOLVED ownership/collaborator consent; MIT is a proposal only |
| SensiFake annotations/metadata | 1101 human,3398 silver in released master | 0804959a6daab0e8041e5120e366580543726905 | Published contribution declares CC BY-NC 4.0 | Keep scope distinct; author approval and compatibility review required |
| OpenFake pilot | 600 (300 Real,300 Fake) | requested v1.0; resolved commit UNRECORDED | v1.0 card: CC BY-SA 4.0, proprietary subsets noncommercial | UNRESOLVED exact pilot revision and generator-specific obligations |
| OpenFake additional | 900 (450 Real,450 Fake) | 750279a9710d3d98bbc6d0d87250312cfdf922a0 | Collected card: CC BY-SA 4.0, proprietary subsets noncommercial | BLOCKER: release blanket CC BY-NC source field does not establish revision/subset rights |
| OpenFake current main | not substituted for collected images | current card separately inspected; changing branch | CC BY-NC 4.0 in current card | Does not retroactively establish terms for collected v1 images |
| SID-Set | 1500 | dc03ead57929879319ce30a82bfcfb8d317b10bd | Dataset card CC BY 4.0; incorporates upstream sources | Retain underlying creator/license/change notices; sample-level attribution review pending |
| RRDataset | 1499 unique,1500 selected paths | Zenodo 14963880; DOI 10.5281/zenodo.14963880 | Official dataset record CC BY 4.0; creators Chunxiao Li,Yao Zhu | Restore paper/source attribution; repository code MIT is not an image license |
| Pretrained/learned weights | V3,ADN,CSN and external benchmark models | checkpoint registry records exact bytes | Code licenses do not automatically cover learned weights/training content | Weights withheld pending ancestry, license and hosting decisions |

## Concrete OpenFake generator evidence

The retained collection manifests preserve generator tags for all 1,500 OpenFake
identities, and every identity is in the pinned SensiFake master. The aggregate
table below contains no prompts, people, annotator records or image bytes.
Tags such as gpt-image-1, Midjourney, DALL-E, Imagen, Ideogram, Flux Pro, Mystic
and Grok identify families requiring specific proprietary-term review. A tag is
not a legal grant, and open-model tags do not prove rights in original content.
The 600-image pilot's exact upstream commit remains absent.

| Generator tag | Pilot-600 | Additional-900 | Status |
| --- | --- | --- | --- |
| chroma | 1 | 1 | UNRESOLVED image/generator terms |
| dalle-3 | 8 | 17 | UNRESOLVED image/generator terms |
| flux-1.1-pro | 9 | 19 | UNRESOLVED image/generator terms |
| flux-amateursnapshotphotos | 2 | 0 | UNRESOLVED image/generator terms |
| flux-mvc5000 | 6 | 8 | UNRESOLVED image/generator terms |
| flux.1-dev | 31 | 51 | UNRESOLVED image/generator terms |
| flux.1-schnell | 5 | 12 | UNRESOLVED image/generator terms |
| gpt-image-1 | 8 | 21 | UNRESOLVED image/generator terms |
| grok-2-image-1212 | 4 | 4 | UNRESOLVED image/generator terms |
| hidream-i1-full | 5 | 17 | UNRESOLVED image/generator terms |
| ideogram-3.0 | 18 | 15 | UNRESOLVED image/generator terms |
| imagen-3.0-002 | 2 | 2 | UNRESOLVED image/generator terms |
| imagen-4.0 | 2 | 4 | UNRESOLVED image/generator terms |
| midjourney-6 | 10 | 24 | UNRESOLVED image/generator terms |
| midjourney-7 | 1 | 0 | UNRESOLVED image/generator terms |
| mystic | 7 | 10 | UNRESOLVED image/generator terms |
| real | 300 | 450 | UNRESOLVED image/generator terms |
| sd-1.5 | 4 | 12 | UNRESOLVED image/generator terms |
| sd-1.5-dreamshaper | 12 | 6 | UNRESOLVED image/generator terms |
| sd-1.5-epicdream | 5 | 11 | UNRESOLVED image/generator terms |
| sd-2.1 | 45 | 63 | UNRESOLVED image/generator terms |
| sd-3.5 | 45 | 69 | UNRESOLVED image/generator terms |
| sdxl | 19 | 22 | UNRESOLVED image/generator terms |
| sdxl-epic-realism | 22 | 22 | UNRESOLVED image/generator terms |
| sdxl-juggernaut | 8 | 14 | UNRESOLVED image/generator terms |
| sdxl-realvis-v5 | 9 | 11 | UNRESOLVED image/generator terms |
| sdxl-touchofrealism | 12 | 15 | UNRESOLVED image/generator terms |

Already-published images include these collected generator families. The release
card's uniform source-license field does not resolve the discrepancy. Determine
the exact grant/attribution for each retained subset; if unsupported, propose a
reviewed HF metadata correction, rights-cleared subset or metadata/retrieval-only
release under separate authorization. No removal or remote relicensing is done
here. CC BY-SA attribution/share-alike duties and its prohibition of additional
restrictions need a concrete compatibility decision; do not assume a blanket
noncommercial contribution notice supersedes the image grant. Conversely, do
not automatically impose an image license on all separate code/annotations.

## Proposals requiring contributor/rights approval

- Original consenting-author code: consider MIT after copied-code and ownership
  review; no MIT text or SPDX declaration has been applied.
- Annotation/metadata contribution: retain the existing declared noncommercial
  scope pending creator agreement and source compatibility analysis. Any change
  to that scope requires separate approval.
- Images: preserve their actual source/image/generator terms and attribution,
  never relicense all imagery as original SensiFake content.
- Weights: obtain separate model cards/terms and pretrained/training-data
  ancestry review; do not ship checkpoint files with a presumed code license.
- Contributors: confirm project author names/order, affiliations and individual
  contributions; retain Git/benchmark authorship. `CITATION.cff.draft` contains
  no invented author list and is not publication-ready.

## Privacy and history

The targeted review found three LOW-risk CSVs and seven REVIEW items, with no
confirmed HIGH exposure. The three LOW files are restored unchanged; the seven
REVIEW files now have minimized public derivatives preserving scientific values,
membership and order. First-name-like labels are not automatically confidential.
See `PRIVACY_PATCH.md` and `privacy_patch_manifest.json` for transformations and
source digests. No original rationale text, SQLite files, annotation packages,
private audit reports, dataset images or model weights were imported. Notebook
outputs/host metadata are removed only in explicitly labelled derivatives.

The existing remote Git history still contains its previously published records.
It was cloned intact, not rewritten. No blanket history purge is recommended on
the findings so far. The targeted reachable-history scan found no confirmed
confidential disclosure or credential exposure, but is not a guarantee that every
possible secret is absent. Public-history and image-identity linkages mean these
derivatives are not anonymous. Contributor attribution/free-text publication
consent remains unresolved; normal author credits and source attribution are
preserved. No private audit evidence or original record was added to Git history.

## Primary sources

- [Collected OpenFake card](https://huggingface.co/datasets/ComplexDataLab/OpenFake/blob/750279a9710d3d98bbc6d0d87250312cfdf922a0/README.md)
- [OpenFake v1.0](https://huggingface.co/datasets/ComplexDataLab/OpenFake/blob/v1.0/README.md)
- [Current OpenFake card](https://huggingface.co/datasets/ComplexDataLab/OpenFake/blob/main/README.md)
- [Pinned SID-Set card](https://huggingface.co/datasets/saberzl/SID_Set/blob/dc03ead57929879319ce30a82bfcfb8d317b10bd/README.md)
- [RRDataset official record](https://zenodo.org/records/14963880)
- [RRDataset official API](https://zenodo.org/api/records/14963880)
- [CC BY-SA 4.0 terms](https://creativecommons.org/licenses/by-sa/4.0/)

Official card/record textual evidence was refreshed on 2026-11-06 and retained
privately with SHA-256 digests. The legal decision is UNRESOLVED; source cards
alone cannot complete an image-level rights review.
