# Pre-fix code review findings

Recorded on 2026-10-16, before implementing any fixes.
Reviewed revision: `c4d6cc0e5ec3904fdb64b350b2656b8e3ff33d53`.

This preserves the fourteen findings from the preceding whole-codebase review;
writing this document is not a second review. All findings remain open at this
revision. P1 means data destruction or incorrect actor attribution to address
first; P2 means a correctness, accounting or validation defect to address next.
The priorities are triage judgments, not measured occurrence rates.

The original observations below remain a pre-fix record. The later
[resolution ledger](#resolution-ledger) records their implementation and
verification in the working tree based on `6cbbb81`.

The behaviors below were exercised through the actual Rust/Python code with
synthetic inputs, except the source-overwrite case, which used a disposable copy
of a public replay export. No original replay, source export or game installation
was modified. Source locations refer to the reviewed revision.

Successful public replay checks do not establish that these boundary cases occur
in ordinary replays. Their real-corpus frequencies remain unmeasured.

## Finding index

| ID | Priority | Finding |
|---|---|---|
| F01 | P1 | [Spike output can replace an input table](#f01-spike-output-can-replace-an-input-table) |
| F02 | P1 | [Empty channel reopen retains the previous actor](#f02-empty-channel-reopen-retains-the-previous-actor) |
| F03 | P2 | [RPC grouping merges different subobjects](#f03-rpc-grouping-merges-different-subobjects) |
| F04 | P2 | [Effect values overread their declared field window](#f04-effect-values-overread-their-declared-field-window) |
| F05 | P2 | [Equal-time ownership changes are reordered by GUID](#f05-equal-time-ownership-changes-are-reordered-by-guid) |
| F06 | P2 | [Plant-time lookup reuses an ended custody interval](#f06-plant-time-lookup-reuses-an-ended-custody-interval) |
| F07 | P2 | [RepLayout accepts EOF without its terminator](#f07-replayout-accepts-eof-without-its-terminator) |
| F08 | P2 | [Array flattening omits zero-width fields](#f08-array-flattening-omits-zero-width-fields) |
| F09 | P2 | [Movement update arrays accept a missing terminator](#f09-movement-update-arrays-accept-a-missing-terminator) |
| F10 | P2 | [Bits outside a sized movement section are uncounted](#f10-bits-outside-a-sized-movement-section-are-uncounted) |
| F11 | P2 | [Short intermediate blocks shift extracted chunk bytes](#f11-short-intermediate-blocks-shift-extracted-chunk-bytes) |
| F12 | P2 | [TOC method counts allocate without an input bound](#f12-toc-method-counts-allocate-without-an-input-bound) |
| F13 | P2 | [Directory completeness counts visits instead of files](#f13-directory-completeness-counts-visits-instead-of-files) |
| F14 | P2 | [Full documentation checks assume a Windows test count](#f14-full-documentation-checks-assume-a-windows-test-count) |

## F01: Spike output can replace an input table

**Location:** `tools/extract_spike_carrier.py:247`, `main`.

The command passes `--out` directly to `atomic_write_file` without calling
`atomic_io.refuse_input_path`. Atomic replacement protects against a failed write,
but does not protect a successfully replaced input.

**Reproduction:** copy a complete export into a disposable directory, then run:

```bash
python tools/extract_spike_carrier.py --export <disposable-export> --out <disposable-export>/fields.parquet
```

**Observed:** exit 0. The original fifteen-column field schema was replaced by
the fourteen-column custody schema, starting with `round_number`,
`bomb_net_guid`, `from_ms` and `to_ms`. This was an actual write to the disposable
copy, not just an intercepted publisher call.

**Impact:** an otherwise successful analysis command destroys its own source
table. Other export inputs can also be selected as the output path.

**Fix acceptance:** refuse aliases of every input before building or publishing
output, including resolved symbolic-link aliases. Keep replacement of a previous
analysis output working, and preserve the atomic writer's hard-link semantics.
`tools/extract_active_effects.py` already uses the shared input-path guard.

## F02: Empty channel reopen retains the previous actor

**Location:** `crates/vrf-net/src/pipeline/mod.rs:577`, `process_bunch`.

A non-partial bunch calls `process_complete_payload` only when its payload is
nonempty. An empty `b_open` therefore bypasses both the failed-open read and
`retire_after_failed_open`.

**Reproduction:** use the existing pipeline packet-builder shapes, in order:

1. Open channel 2 for static actor 3, carrying one empty actor content block.
2. Send a reliable, non-partial open on channel 2 with no payload.
3. Send a non-open bunch on channel 2 carrying another empty actor block.

**Observed:**

```text
empty reopen: actors=[3, 3], header_failures=0, failed_reopens=0, unopened=0
one-bit reopen control: actors=[3], header_failures=1, failed_reopens=1, unopened=1
```

**Impact:** subsequent content remains attributed to the displaced actor with
clean failure counters. In the CLI sink that can retain the wrong class/schema.

**Fix acceptance:** a missing actor GUID on a complete open must enter failed-open
accounting and retire the previous actor; later bunches must be reported as
unopened, without fabricating a close. Keep ordinary payload-less close behavior.
This is separate from the rejected-partial-open limitation already recorded in
[FOLLOWUP.md](FOLLOWUP.md).

## F03: RPC grouping merges different subobjects

**Location:** `tools/to_valplay_bundle.py:1388`, `_group_rows`.

RPC groups use `(packet_id, actor_net_guid, group_path, handle)`. The property
groups include `object_net_guid`, but the RPC groups omit it.

**Reproduction:** two rows share packet 5, actor 3, group
`/Script/Test.Comp_ClassNetCache` and handle 7, but name objects 20 and 30.
Their parameter names are `Fn.A` and `Fn.B`.

**Observed:** one RPC group contains both row indices, `[0, 1]`.

**Impact:** calls on separate components become one invocation. Parameters can
overwrite each other or form a combined payload that no component sent.

**Fix acceptance:** retain object identity through grouping and its consumers,
including the distinction between actor rows (`None`) and a real object GUID.
The existing limitation concerning repeated calls on the same object is separate.

## F04: Effect values overread their declared field window

**Location:** `tools/to_valplay_bundle.py:651`, `_decode_effect_elements`.

`spec.read_value` receives the whole array reader rather than a reader bounded
to `payload_bits`. The subsequent consumption check handles underreads only.

**Reproduction:** call `_decode_effect_elements` with each complete synthetic
blob's exact bit count, `_EFFECT_FLOATS`, and an empty tally:

| Declared float width | Hex input |
|---|---|
| 1 bit | `020210100212020000803f0000` |
| 32 bits, control | `020210100212400000803f0000` |

**Observed:** both return `[(1, 1.0)]`, with `tally == {}`.

**Impact:** bits outside a leaf's declared window can become a plausible typed
value without any loss signal.

**Fix acceptance:** bound both tag and value reads to their declared field
windows; reject or count malformed windows without consuming neighboring fields.
The correctly sized control must continue to decode.

## F05: Equal-time ownership changes are reordered by GUID

**Location:** `tools/extract_spike_carrier.py:187`, `build`.

`owner_log` stores `(time_ms, owner)` and calls `log.sort()`. Equal times are
therefore ordered by owner GUID rather than wire order. The loader discards the
packet ID that could distinguish these writes.

**Reproduction:** bomb 900 has successive owners `[2, 9, 1]` at times
`[100, 200, 200]`.

**Observed:** extracted owner order is `[2, 1, 9]`, making owner 9 the final owner
instead of owner 1. This exercised `build` with synthetic loaded rows and an
empty player-identity result; it did not depend on classification.

**Impact:** custody after the tied timestamp can remain assigned to the wrong
owner until another write arrives.

**Fix acceptance:** retain packet/physical row ordering for tied timestamps and
test final-owner lookup after the tie. Do not use GUID order as event order.

## F06: Plant-time lookup reuses an ended custody interval

**Locations:** `tools/extract_spike_carrier.py:79`, `carrier_at`, and
`tools/extract_spike_carrier.py:92`, `unresolved`.

`carrier_at` includes `to_ms`. Its callers first remove loose and unknown
intervals, so a transition to a non-carrier can leave only the former carrier
eligible at the shared boundary.

**Reproduction:** player custody spans 100--200 ms, loose custody spans
200--300 ms, and `spikePlanted` is at 200 ms.

**Observed:** `unresolved` returns `[]`; the ended player interval satisfies the
plant-time carrier check.

**Impact:** a temporal ambiguity is silently accepted as positive player
attribution.

**Fix acceptance:** define and test interval endpoints and event ordering at a
custody transition. A boundary shared with loose/unknown custody must not be
resolved to the old player merely because non-carriers were filtered out.
Whether a plant legitimately precedes a same-time close needs an explicit rule,
not an unqualified switch to half-open intervals.

## F07: RepLayout accepts EOF without its terminator

**Location:** `crates/vrf-net/src/field.rs:120`, `parse_rep_layout_impl`.

The remainder starts as `RepLayoutRemainder::None`. The loop can finish at EOF
without ever reading encoded handle zero.

**Reproduction:** run the public `parse_rep_layout` over a one-bit, zero-valued
window containing only the property-checksum bit. Compare it with a nine-bit
window containing the checksum bit and an eight-bit zero handle.

**Observed:** both return `Ok((0, 0))`.

**Impact:** a stream missing the grammar's terminator is indistinguishable from a
complete empty stream, so the pipeline's stream-failure counters do not move.

**Fix acceptance:** distinguish a consumed zero terminator from exhaustion at a
record boundary. Preserve already emitted fields and existing valid
post-terminator ClassNetCache-tail handling.

## F08: Array flattening omits zero-width fields

**Location:** `crates/vrf-decode/src/array.rs:320`, `walk_fields`.

`payload_bits == 0` continues before invoking the field sink. The field's
presence disappears from flattened output even though zero width can encode a
real value; `decode/scalar.rs` explicitly treats a zero-width enum as value zero.

**Reproduction:**

```rust
let mut stats = ArrayDecodeStats::default();
let fields = decode_struct_array_exact(&[2, 2, 2, 0, 0, 0], 48, &[], &mut stats);
```

The synthetic bytes encode capacity 1, element 0, handle 0 with a zero-bit
payload, then element and array terminators.

**Observed:** one element, zero leaves, `fields_emitted == 0`, and
`stats.is_clean() == true`. A one-bit payload control emits one leaf.

**Impact:** parent raw data survives, but a present child field and its possible
typed zero value are omitted without an anomaly.

**Fix acceptance:** preserve zero-width leaf presence and its exact window.
Review the existing `exactly_max_fields_followed_by_a_terminator_is_not_truncated`
test, whose expected leaves currently encode the omission, rather than silently
changing that test as incidental cleanup.

## F09: Movement update arrays accept a missing terminator

**Location:** `crates/vrf-movement/src/rpc.rs:70`, `decode_updates_array`.

The array loop considers exhaustion a normal end without establishing that the
zero index terminator was read.

**Reproduction:** call `decode_movement_rpc` on bytes
`[0x08, 0x20, 0x04, 0x00, 0x00]`, bounded to 33 bits.
The updates property contains only `updateCount = 1`; the top-level RPC
terminator is present.

**Observed:** `update_count=1`, `total_moves=0`, `error_count=0`.

**Impact:** the inner array's truncation is hidden by the valid outer framing.

**Fix acceptance:** count or reject premature array exhaustion while preserving
valid sparse-update behavior. Do not require the number of changed elements to
equal the declared array capacity.

## F10: Bits outside a sized movement section are uncounted

**Location:** `crates/vrf-movement/src/rpc.rs:193`,
`parse_movement_with_bit_count`.

The decoder bounds a sub-reader to a nonzero `movementBitCount`, but never
accounts for the enclosing reader's bits after that window. Section-tail
counters cover only the inside, and envelope-trailer counters cover a different
boundary.

**Reproduction:** wrap this direct component stream in a valid update/RPC using
the shapes in `crates/vrf-movement/src/tests.rs`:

```text
u16(11), u8(0x52), three-bit zero movement marker, u8(0xff)
```

The declared eleven-bit movement section is complete. Compare with the same
stream without the final byte.

**Observed:** both controls have `error_count=0`, `sized_section_tail_bits=0`,
`open_section_tail_bits=0`, and `envelope_trailer_bits=0`.

**Impact:** the extra eight bits are unexplained and unreported. A successful
movement RPC need not retain duplicate raw input, so this is not just a display
omission.

**Fix acceptance:** expose the remainder outside the sized section separately
from existing inside-section and outside-envelope populations; preserve the
current measured distinctions rather than folding unrelated counters together.

## F11: Short intermediate blocks shift extracted chunk bytes

**Location:** `tools/extract_component_classes/src/container.rs:58`,
`Container::read_chunk`.

Block positions are computed using `toc.block_size`, but output concatenates the
actual decoded lengths. Only the final combined length is checked.

**Reproduction:** use the existing TOC helper with:

```text
one_chunk_toc(1, (0, 12), 8, [], [(0, 4, 4, 0), (4, 8, 8, 0)])
```

Both blocks are stored/uncompressed; the backing bytes are 0 through 11.
TOC parsing accepts the input.

**Observed:** `read_chunk(..., u64::MAX)` returns
`Ok([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11])`.

**Impact:** virtual positions 4--7 are absent from the first eight-byte block,
but bytes from the next block slide into that gap instead of causing an error.
Package readers can receive plausible bytes at the wrong offsets.

**Fix acceptance:** validate each block's required virtual span before appending
it, including partial-chunk reads and legitimate short final blocks.

## F12: TOC method counts allocate without an input bound

**Location:** `tools/extract_component_classes/src/toc.rs:166`, `parse_toc`.

The method-name vector reserves the wire count directly, unlike the bounded
chunk/block vectors. A zero method-name width lets iterations consume no input.

**Reproduction:** start with an unsigned empty TOC built by the existing test
helper. Set the little-endian u32 at offset 36 to 4096 and the u32 at offset 40
to zero.

**Observed:** the 148-byte input parses into 4096 empty method names.

**Impact:** allocation and work scale with an unchecked count rather than the
available bytes. Larger counts can exhaust resources. The executed probe kept
the count bounded; no out-of-memory experiment was performed.

**Fix acceptance:** establish the table's physical byte requirement and supported
name width before allocation; reject zero-width nonempty method tables.

## F13: Directory completeness counts visits instead of files

**Location:** `tools/extract_component_classes/src/dirindex.rs:106`,
`DirectoryIndex::files`.

The completeness guard compares output length with the file-table length.
Different directories can visit the same file entry, balancing an unreachable
file entry.

**Reproduction:** use `build_index` with `NONE = u32::MAX`:

```text
mount: "/"
dirs: [(NONE, 1, NONE, 0), (0, NONE, NONE, 0)]
files: [(1, NONE, 0), (2, NONE, 1)]
strings: ["Sub", "a.uasset", "b.uasset"]
```

**Observed:** `files()` succeeds with
`[("/a.uasset", 0), ("/Sub/a.uasset", 0)]`.
`b.uasset` is never reached.

**Impact:** duplicate visits can hide an incomplete listing and skew subsequent
asset scans.

**Fix acceptance:** track visited file identities and reject duplicate or
unreachable entries, while retaining cycle and out-of-range detection.

## F14: Full documentation checks assume a Windows test count

**Locations:** `tools/check_docs.py`, `measure_tests`/`main`, and the
Windows-only test at `crates/vrfkit/src/driver/publish.rs:659`.

The full guard compares the local Rust suite count with the Windows-derived
count quoted by README and USAGE. The publication test is correctly gated to
Windows, where the tested filesystem refusal exists.

**Reproduction:** on macOS, with Rust 1.86 and Python dependencies available:

```bash
python -W error tools/check_docs.py
```

**Observed:** Rust reports 707 passing, Python 1045, and the command exits 1 with
six stale/missing claims. README and USAGE quote 708 for Rust. The `--fast`
documentation check passes.

**Impact:** the documented full contributor sweep fails on macOS even when its
runtime suites pass. This is not evidence that hosted Windows CI failed.

**Fix acceptance:** make the measurement platform-aware or explicitly scope the
quoted count and full count check to its platform. Keep detection of genuine
stale counts; do not rewrite the Windows count to match macOS.

## Verification snapshot

These are results from the preceding review at the revision above, not new
results produced by writing this document:

- On macOS arm64, Rust 1.86: 707 passing with all workspace features enabled;
  fmt, Clippy with warnings denied, strict rustdoc, core-only CLI/container
  runs and all 27 metadata-derived feature cases passed.
- Python 3.12: 1045 passing; the ASCII, type-correction, generated checksum,
  scoped-type, baseline-schema and fast documentation guards passed.
- Rust-to-PyArrow interoperability passed.
- The pinned public 12.10, 12.11 and 13.00 fixtures passed validation,
  checkpoint-enabled export and independent typed/raw comparison. All fixture
  hashes were checked against CI's pinned values.
- The main stream scored 29,046 blocks, checkpoints contained 4,207 blocks,
  and 582 independently compared values had no typed mismatch. The public
  container corpus smoke check also passed on all three inputs.
- `inspect --redact-identifiers` emitted the redacted label. `diag` reconciled
  preserved failures with no real loss on the public 12.10 input.
- The full documentation guard failed as recorded in F14.

The private 1,018-replay audit was not rerun. Windows packaging/runtime checks
and native executable recapture were not run. Generated vectors were not
independently re-derived. This review does not replace the historical evidence
in [BUILD_VERIFICATION.md](BUILD_VERIFICATION.md).

## GitHub snapshot

Checked on 2026-10-16 through the repository's paginated GitHub API and the
individual Issue/PR pages. This is a snapshot, not a live status display:

- Issue `yakisoba0728/vrfkit#33`, **Support VALORANT build 13.08**, is open.
  Created 2026-10-15, labelled `bug`, with no comments at the check. Its selected
  branch field says `release-13.06`, but the diagnostic log explicitly names
  `++Ares-Core+release-13.08` and reports an unregistered payload transform.
- PR `yakisoba0728/vrfkit#32`, **Add VALORANT 13.08**, is open and not a draft,
  by `SunkenInTime`, targeting `main` from `build/13.08`. Its head is
  `4dfdd2137808b5a0cc6c35d7d0e178ec421b4110`, with two commits and ten changed
  files. It adds a transform, 79 native vectors, an empty measured-array-route
  test row and supporting evidence/docs.
- The PR's API response has no review, conversation or status-check entries.
  GitHub reports `mergeable=MERGEABLE` but `mergeStateStatus=UNSTABLE`;
  absence of a textual merge conflict is not a green-check result.
- Its head has one CI workflow run, `38677455508`, with
  `conclusion=action_required`. The run page explicitly says it is awaiting
  maintainer approval. The empty check list therefore must not be described as
  passing CI.
- The contributor reports validation/export success on two 13.08 replays but
  only one strictly clean audit. The other stops at two case-only checkpoint
  GUID-path disagreements (`Sphere` versus `sphere`). The proposed explanation
  is case-insensitive FName reuse; the checkpoint writer was not inspected.
  These replay results are contributor-reported, not locally reproduced here.
- PR #32 targets the unsupported-build symptom in Issue #33, but does not fix
  any F01--F14 implementation. No automatic closing relationship was observed.

Issue and PR content, changed implementation paths, comments, review comments
and check metadata were read without checking out or executing the PR.
No GitHub comment, review, issue edit, workflow approval or merge was submitted.

## Fix order and completion evidence

Address F01/F02 first, then RPC identity and window boundaries, custody ordering,
parser accounting, asset-reader validation and the platform count guard.
F06 needs an explicit event-boundary decision before implementation.

For each fix, retain its ID and record the implementation revision, a regression
that fails on the reviewed revision, relevant passing checks and any real-replay
before/after results. Preserve raw payloads and surface anomalies instead of
inventing values. Do not mark a finding fixed from compilation or a rounded
oracle percentage alone.

## Resolution ledger

Implemented on 2026-10-16 in the uncommitted working tree based on
`6cbbb81e71a16afbfd8721b70257428f2830d804`, after PR #32 was merged.
There is no new implementation commit to cite. This section does not replace
the original revision's measurements or its GitHub snapshot.

Every F01--F14 item below has a failing-before regression and passing-after
coverage. The F11 oversized-block case additionally failed the initial
minimum-span fix before the parent completed the virtual-stride invariant.

| ID | Corrected behavior | Regression evidence |
|---|---|---|
| F01 | Refuse resolved aliases of all four source inputs before building or publishing. Existing analysis replacement and safe hard-link replacement remain valid. | `ReconnectedCarrierTests.test_input_paths_and_symlink_aliases_are_refused_before_build` exercises direct paths and symlink aliases; the companion replacement test retains the atomic writer's contract. |
| F02 | A complete empty open enters failed-open accounting and retires the displaced actor. Later content is unopened, with no fabricated close. | `pipeline::tests::an_empty_reopen_retires_the_previous_actor`; one-bit reopen and payload-less close controls remain passing. |
| F03 | RPC grouping and its consumers retain nullable subobject identity. Different objects cannot merge because their other invocation keys agree. | `RpcObjectIdentityTests` exercises distinct subobjects, actor-null identity, actual RPC events and shots. |
| F04 | Both effect tag and value readers are bounded to their declared field windows. Short reads cannot borrow neighboring bits. | `EffectPayloadWindowTests` covers the recorded malformed float, short tags, scalar/object/vector values, neighboring elements and raw-source preservation. |
| F05 | Timestamp ties sort by packet ID and then stable physical row order, never owner GUID. | `ReconnectedCarrierTests.test_equal_time_writes_keep_packet_then_physical_row_order` checks the final owner after both kinds of tie. |
| F06 | Plant lookup considers the whole custody timeline. Unordered transitions involving another owner, loose/unknown custody, or terminal close remain unresolved. | `CarrierAtTests`, `UnresolvedTests`, and the real CLI before/at/after a drop. Repeated same-owner ties remain resolvable. |
| F07 | EOF is not a consumed zero handle. A missing RepLayout terminator enters existing stream failure accounting without discarding emitted fields. | `field::tests::rep_layout_checksum_only_requires_a_terminator` and pipeline prefix-preservation/failure tests; valid ClassNetCache tails still pass. |
| F08 | Zero-width struct leaves retain their presence, empty raw window and possible enum-zero value. | `array::tests::a_zero_width_leaf_preserves_presence_and_decodes_as_enum_zero`, nested empty-leaf coverage and a positive-width float control. |
| F09 | Updates arrays require their own zero index terminator even when outer RPC framing is complete. Sparse capacity remains independent of changed-element count. | `boundary_tests::missing_array_terminator_is_counted_when_outer_rpc_is_complete` and the actual sink raw-retention test. |
| F10 | Components and bits after a fitting sized movement window have separate result, sink, manifest and main/checkpoint summary tallies. | `boundary_tests::component_remainder_is_accounted_when_sized_section_is_complete`, independent field-by-field sums and main/checkpoint zero/nonzero controls. |
| F11 | Every intermediate decoded block must exactly fill its virtual stride; the final touched block must supply the requested prefix. Neither short nor oversized intermediates can shift later bytes. | Short, oversized and cross-boundary prefix regressions, valid bounded prefixes and legitimate short final blocks; the asset package passes all 69 cases. |
| F12 | A nonempty method table requires the supported 32-byte name width and a physically available complete table before allocation or iteration. Empty tables remain valid. | `toc::tests::nonempty_zero_width_method_tables_are_rejected`, unsupported-width and short-input controls; no OOM experiment. |
| F13 | Directory completeness counts distinct file-table identities. Repeated visits cannot conceal unreachable files. | `dirindex::tests::duplicate_file_visits_cannot_balance_an_unreachable_file`, no-root/unreachable cases, and existing range/cycle controls. |
| F14 | Suite-size claims can be qualified for Windows or non-Windows; each full run still measures both suites and rejects stale, missing or failed measurements for its platform. | `PlatformTestCountTests`, existing measurement-failure tests, and the full guard on macOS. |

### Custody boundary decision

Owner writes retain packet and physical row order. Plant events have no packet
key comparable to those writes or actor closes, so timestamp equality alone
cannot establish plant-before-transition or plant-after-transition.
`carrier_at` includes both candidate interval endpoints, without removing loose
or unknown intervals. Attribution requires the candidates to identify the same
carried bomb/owner and not end at a terminal close at that timestamp. Otherwise
the plant is unresolved and the command exits nonzero. This is not a blanket
half-open-interval rule.

### Separate Windows CI input-lifetime fix

The post-merge run `38839239321` failed in
`CoverageTextTests.test_unattributed_rows_are_counted_without_becoming_named_coverage`
while deleting a temporary `fields.parquet`, with `PermissionError:
[WinError 32]`. The ensuing Python count errors were consequences of the
failed module, not the F14 macOS count difference.

The three single-file field readers in `compare_with_csharp.py` now own
context-managed `ParquetFile` inputs with prebuffering disabled. Real-reader
lifetime tests retain the reader objects and require closure before normal or
exceptional return; the original read exception must propagate unchanged.
Removing only the coverage reader's context manager makes both lifetime tests
fail, and restoring it makes them pass. No cleanup retry, delay, ignored
failure, skipped test or reduced suite count was introduced.

This establishes deterministic local reader ownership. It is not a claim that
a new hosted Windows CI run has succeeded or that an arbitrary external process
cannot hold a file.

### Integrated verification and method

- On macOS arm64 with Rust 1.86, the final all-feature workspace run passes
  737 cases. Fmt, workspace Clippy with warnings denied, strict rustdoc,
  core-only CLI/container tests, all 27 metadata-derived feature cases and the
  exact Rust-to-PyArrow interoperability directory pass.
- Python 3.12 with the repository requirements passes all 1072 cases with
  warnings treated as errors. The full documentation guard independently runs
  the Rust suite and each Python module, measures the platform's counts and
  exits zero. ASCII checks include the untracked movement boundary test file.
  Type corrections, generated checksum/scoped types and all 11 committed
  baseline schemas pass.
- The declared Windows suite size is 738 because the existing publication
  refusal test is Windows-only. That number is not a local Windows execution
  result.
- The pinned public 12.10, 12.11 and 13.00 fixtures pass the common
  `verify_build_corpus.py` audit with checkpoints and independent typed/raw
  comparison: 29,046 scored main blocks, 4,207 checkpoint blocks and 582
  compared values, with no width failure or typed mismatch.
- Fresh validation logs match every committed per-file and aggregate oracle
  value in the three public `build_*.json` baselines. All thirteen Parquet
  files per input, 39 files total, have identical SHA-256 hashes to their
  pre-fix exports. The production CLI was restored after test builds and its
  hash matches the binary used for this audit.
- The actual `validate_corpus.py` and checkpoint-enabled
  `check_decode_errors_corpus.py` commands pass on all three fixtures. Array,
  overlay, movement and parameter-walk work counters move; all 15 failure
  counters are zero in each enabled pass. Sized-window populations without
  a must-move denominator remain explicitly labelled unbacked.
- The actual adapter and spike-carrier CLIs succeed on each public export.
  They write three bundles and 19 custody intervals total. RPC-parameter
  collisions, half-read effect pairs and effect residual counters are zero
  on these inputs; this does not cover every malformed boundary case.

The new movement observations are required, reconciled against the manifest
and printed from the central summary registry. They are not filled with assumed
zeros in historical private baseline snapshots. The common audit and decode
gate reject a missing or nonzero outside-window counter.

The original F08 field-limit expectations omitted already-walked zero-width
leaves. Only those stale leaf expectations changed; their error/truncation
assertions remain. Other integration fixture updates add the real packet IDs,
new summary lines and explicit subprocess encoding, rather than weakening the
guards that detected them.

### Remaining verification limits

- The private 1,018-replay corpus, the two private 13.08 replays and the original
  native executable readers were not rerun or recaptured. Public output
  stability does not measure each finding's frequency on those inputs.
- No installed-game asset extraction was performed. F11--F13 use the actual
  parser/container/directory code with synthetic, physically bounded inputs.
- New hosted Windows checks, optimized Windows packaging and Python 3.13 were
  not executed for these uncommitted changes. The earlier run is still a failed
  run, not rewritten as passing evidence.
- Rust-analyzer and basedpyright diagnostics were unavailable locally.
  Compiler, strict Clippy and warnings-as-errors runtime checks passed instead.
- No implementation commit, push, release, GitHub message or new workflow
  dispatch was made by this fix pass.

### PR #34 Windows CI follow-up

The first PR workflow, run `38849410354` at `75258b4`, passed the four
Windows/Ubuntu Python matrix jobs, Rust stable, and optimized Windows
packaging with its packaged replay audit. Its MSRV job passed 738 Rust tests
but failed the per-module Python run inside the full documentation guard.
Three additional input cleanup paths reported `WinError 32`:
`extract_active_effects` on actors, `extract_rounds` on events, and
`section_timeline` through the shared `wire_bits.iter_selected` actor scan.
The earlier comparison-reader fix did not fail in this run.

The first two paths now own context-managed, non-prebuffered `ParquetFile`
inputs. The shared batch iterator also owns its reader until exhaustion,
filter failure, or explicit generator closure. Retained real-reader assertions
strengthen the existing failing paths, including the cross-batch ordinal test;
two new cases cover filter errors and early closure. Test cleanup does not
close the retained readers until after the ownership assertions.

All five ownership checks fail before this follow-up and pass afterward.
The three affected modules pass 57 tests, and the full local guard measures
737 non-Windows Rust cases and 1074 Python cases and exits zero. The failing
Windows run's incomplete Python count of 1017 is not a new suite-size claim.
No retry, delay, ignored cleanup failure or skipped test was added.

Run `38850551061` at `12d60d9` no longer reports the three source-input
failures. Its remaining error is the active-effects CLI test's own read of
`tracks.parquet` during the output assertion. That assertion now uses an
owned `ParquetFile` as well, preserving the same row-count check and closing
the output before temporary-directory cleanup. This is a fixture-lifetime
correction, not a change to the analysis output or the expected suite count.

Run `38851438274` at `eb2f062` exposes the same fixture ownership problem
in the rounds CLI test's `rounds.parquet` assertion. The test fixture audit
finds 22 remaining single-file `pq.read_table` calls without options.
They now use the shared test-only `read_parquet` helper, which materializes
the real table inside an owned reader and closes it before returning.
Read-before-rewrite fixtures keep their same data transformations; output
assertions keep their same schema, column, row and value expectations.
The rounds CLI test retains real reader references until after its ownership
assertions. No global Arrow monkeypatch or production abstraction is added.

The eight affected modules pass 298 tests, and the full local guard still
passes 737 non-Windows Rust and 1074 Python cases. Removing only the helper's
context manager, while retaining its real reader and read, makes the rounds
ownership assertion fail on an open reader. The context is restored before
publication. This tests actual closure rather than only reader selection.
