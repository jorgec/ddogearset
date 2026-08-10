> **Responses added 2026-08-10.** Each objection is answered inline below under
> a `#### RESPONSE` heading. Verdicts: **4 adopted**, **1 adopted with its
> conclusion reversed**, **1 rejected on measurement**. The same adjudication is
> recorded in
> [`01_RECALC_SPEC_AND_PHASED_PLAN.md`](01_RECALC_SPEC_AND_PHASED_PLAN.md) §7,
> and every accepted change is folded into the phase it affects.

---
### 1. Payload Inflation vs. the Wails Bridge (The Biggest Risk)                                                                                           
                                                                                                                                                             
  • The Catch: The retrospective (§2.3) explicitly warns that the Wails bridge silently drops payloads >64KB, which causes the UI to hang.                   
  • The Miss: In 01_RECALC_SPEC_AND_PHASED_PLAN §3.3, you propose changing allEffects from a list of flat strings ("12.0 Insightful (Legendary Bracers...)") 
  to a list of structured JSON objects ({"value": 12.0, "bonusType": "Insightful", "source": "Legendary..."}). This will significantly inflate the byte size 
  of the payload. If a fully-geared character has hundreds of effects, this JSON bloat might push the response payload directly into the Wails danger zone   
  you are trying to avoid.                                                                                                                                   
  • Recommendation: Upgrade to Wails v3                        
                                                                                                                                                             

#### RESPONSE

**Verdict: rejected on measurement.** The concern is sound discipline aimed at a
number that isn't there.

Measured across all 13 real `.ddogearset` files that carry a result:

| | Today (strings) | Structured | Delta |
|---|---|---|---|
| `allEffects` alone | 1.9 – 3.4 KB | 3.1 – 5.4 KB | +56 – 68% |
| **Whole response** | **10 – 18 KB** | **12 – 20 KB** | **+~2 KB** |

Real gearsets carry **36–57 effects**, not hundreds — a fully-geared 14-slot
caster is the top of that range, not the middle. And the measured cliff is 64 KB
**arguments at concurrency 40** (retrospective §2.3); this is a ~20 KB **return
value** on a single call. There is roughly a 3× margin before the danger zone,
and the change spends 10% of it.

Two further points against the remedy:

- **Wails v2.10 → v3 is a whole-app migration** — different app API, different
  binding generation, different runtime — offered as a fix for a 2 KB delta. It
  would be the largest single change in the project, taken on speculation that
  v3 behaves better, which is not established.
- **Bridge pressure is already being reduced elsewhere in the plan.** Both
  contributing factors the retrospective names are self-inflicted and scheduled:
  the unbounded `GetSystemLogs` re-sent every second (Phase 7) and the load path
  sending the whole file across twice (Phase 8, checksum made advisory).

**What is adopted is the discipline, not the remedy.** The Phase 6 gate now
carries `e2e_bridge_payload_ceiling`: record the real recalculate and solve
response sizes and **fail if either exceeds 32 KB** — half the measured cliff.
That converts "the payload is fine" from an argument into an assertion that
breaks if a future change makes it untrue.

*Landed:* §3.3 (measurement table), Phase 6 gate, §6 out-of-scope.

---

  ### 2. Physical Validation is Net-New Code                                                                                                                 
                                                                                                                                                             
  • The Catch: The proposal (§5.4) states that physical rules (minor artifacts, filigree counts, augment colors) will become "observations" (warnings) rather
  than solver constraints.                                                                                                                                   
  • The Miss: The documents treat this as a simple reporting change, but those constraints currently live inside the ILP model (create_model). If recalculate
  bypasses create_model entirely, who is computing these warnings? You will need to write net-new, pure Python validation logic to inspect the gearset and   
  emit these warnings, effectively reimplementing the validation that the ILP constraints used to handle for free.                                           
  • Recommendation: Acknowledge this scope. Add a specific step in Phase 3 to implement and test validate_physical_rules(gearset) as pure Python functions.  
                                                                                                                                                             

#### RESPONSE

**Verdict: adopted in full.** This is a correct catch and the draft understated
it — §3.5 listed the warnings without scoping the work to produce them, which
reads as though they fall out of the resolution step. They do not: these
constraints exist today only as ILP rows in `create_model`, and bypassing the
model means writing them.

Phase 3 now has an explicit step, sequenced **before** the response assembler so
`warnings` is a real input to it rather than an afterthought:

> **`validate_physical_rules(resolved_gearset) -> [warning]`** — pure Python, its
> own module in `python/rules/`, its own unit tests.

Two refinements from reading the code:

- **"One item per slot" needs no check at all.** `pre_equipped` is a slot→name
  map, so the constraint is unviolatable by construction. Writing a check for it
  would be dead code.
- **The colour check is cheaper than it looks.** `_item_from_node` already
  extracts each item's `<ItemAugment>` slot colours (`optimizer.py:944`), so
  augment-colour compatibility is a set comparison against data the resolver
  already has, not new parsing.

Phase 4's §14.4 tests (`test_physical_violations_warn_and_still_total`,
`test_warning_is_specific`) then verify the behaviour rather than assuming it.

*Landed:* §3.5, Phase 3 step 3.

---

  ### 3. UX Mismatch on Multi-Target Effects (Phase 7)                                                                                                       
                                                                                                                                                             
  • The Catch: 01_RECALC_SPEC_AND_PHASED_PLAN (Phase 7) says Go will be updated to parse <Item> as []string so the UI can display all targets (e.g., "Force, 
  Physical, Untyped"). However, Python will continue to only credit the first target ("Force") because fixing Python's math is deferred to a separate task   
  (Decision 8).                                                                                                                                              
  • The Miss: This creates a direct crisis of trust in the UI. The user will see their item explicitly claiming to grant "Physical" and "Untyped" power in   
  the tooltips, but their stat totals won't reflect it. This is arguably worse than the current state where the UI simply says "Force" and credits "Force"   
  (even if incomplete).                                                                                                                                      
  • Recommendation: Do not update the Go display model to []string until you are also ready to fix the Python crediting rule. They must move in lockstep.    
                                                                                                                                                             

#### RESPONSE

**Verdict: constraint adopted, conclusion reversed.**

The trap is real and the constraint is now written into the plan verbatim. But
the proposed remedy — leave Go alone until Python's crediting changes — rests on
a premise that doesn't hold: *"arguably worse than the current state where the UI
simply says 'Force' and credits 'Force'."*

**The UI does not say "Force" today. It says "Untyped".** Go's `Item string`
keeps the **last** `<Item>` element, Python's `findtext` takes the **first**, and
`ItemDetail.svelte:100` uses that field as the buff's display label
(`buffLabel` → `b.Item || b.Type`). So for Miserable Arcana the panel is already
labelling the buff `Untyped` while the maths credits `Force`. Display and
arithmetic already disagree, and they disagree in the direction that shows the
user a stat their totals genuinely do not include.

Deferring therefore preserves the crisis of trust rather than avoiding it.

**The fix is `[]string` in the model with the display bound to `Item[0]`, and
only `Item[0]`.** The slice exists so Go can know which target is *first* —
matching Python — not as a licence to render "Force, Physical, Untyped". With
that constraint the change is strictly corrective: it moves the label onto the
element the arithmetic actually uses, and display and maths move in lockstep
because they read the same element. Revisit the display when the multi-target
investigation (decision 8) concludes.

*Landed:* Phase 7, as a blockquote constraint attached to the change itself so it
cannot be implemented without it.

---

  ### 4. The extractSolver I/O Penalty (Phase 5)                                                                                                             
                                                                                                                                                             
  • The Catch: Moving to PyInstaller --onedir fixes the 3.8s UPX unpack penalty, but relies on Go's extractSolver to dump the directory to a temp folder     
  (app.go:334).                                                                                                                                              
  • The Miss: If Go writes 8MB+ of files to tmp on every single app startup (or worse, every calculation), you are simply trading PyInstaller's CPU unpack   
  penalty for a Go disk I/O penalty. You might not hit the 0.12s goal on slower drives or restrictive antivirus environments.                                
  • Recommendation: Ensure Go's extractSolver hashes the binary/directory (or checks a version file) and only extracts it if it doesn't already exist in the 
  temp/appData path.


#### RESPONSE

**Verdict: adopted.** And the numbers are worse than the objection assumes.

Measured on the `--onedir` build:

| | Files | Size |
|---|---|---|
| Today (`--onefile` + UPX) | 2 | 7.9 MB |
| `--onedir` | **55** | **20 MB** |

One correction to the framing: extraction is **not** per calculation.
`runSolver` only calls `extractSolver` when `a.solverPath == ""`, and the path
is cached for the process, so it is once per app **launch**. That is still 20 MB
across 55 files on every launch, for a bundle that changes only when the app is
updated — and it is exactly as unpredictable under antivirus as the objection
says.

Phase 5 now requires:

- extraction to a **stable, version-stamped path**
  (`<cache>/ddo-solver/<AppVersion>-<hash>/`), not a random `MkdirTemp`;
- a `.stamp` file **written last**, so a partial extraction is never mistaken for
  a complete one;
- startup skipping extraction entirely when the stamp matches.

Extraction then happens **once per install**, not once per launch, and the gate
asserts it: *second and subsequent app launches perform zero extraction I/O*.

One knock-on the objection doesn't mention but that follows from the same
numbers: the embedded bundle grows from 7.9 MB to 20 MB **inside the Go binary**,
since `go:embed` stores it uncompressed. If that binary growth matters, embed a
zip and expand it during the one-time extraction — with caching in place the
decompression cost is paid per install, which is the whole point of the change.

*Landed:* Phase 5 body and gate.

---

    ### 5. 0.5.0 vs 0.5.1 Phase Split Awkwardness                                                                                                              
                                                                                                                                                             
  • The Catch: 0.5.0 implements otherStats (unprioritized stats) in the backend, but the UI overhaul to display them is deferred to 0.5.1 (UI doc). Phase 6  
  says Summary.svelte gets a "minimal update" to surface warnings, but leaves the layout untouched.                                                          
  • The Miss: Computing otherStats, serializing it, sending it over the fragile Wails bridge, and then having Svelte throw it away for an entire release is a
  waste of bytes and processing time. Furthermore, squeezing the new warnings into the old Summary.svelte layout without breaking it is likely to be harder  
  than expected, given you're about to throw that layout away in 0.5.1 anyway.                                                                               
  • Recommendation: Do not send otherStats in the Wails payload in 0.5.0. Wait until 0.5.1. Keep the "minimal update" for warnings in 0.5.0 strictly to a    
  simple text list or toast so it doesn't become a layout time-sink.                                                                                         
                                                                                                                                                             

#### RESPONSE

**Verdict: split — the `otherStats` half rejected, the layout half adopted.**

**On withholding `otherStats`: rejected, on two grounds.**

*Measurement.* The 14 equipped items of a full caster gearset expose **34
`<Buff>` nodes in total**, of which **12 stats are already reported**. Augments,
filigrees and sets add a similar order. `otherStats` is therefore tens of
entries and **~1–2 KB** on a 10–18 KB response — not a meaningful share of
"bytes and processing time", and computing it is a dictionary insert on data the
aggregation has already walked.

*Churn.* `otherStats` is asserted on by the Phase 4 differential suite, so it has
to exist and be correct in 0.5.0 regardless of whether Svelte reads it.
Withholding it from the wire means changing the response contract **twice** —
once to add the key, once to ship it — and the response is persisted into the
save file. Retrospective §2.4 is precisely about paying a user-facing migration
for every change to a derived shape; the answer there was to settle the shape
once. Sending a key the UI ignores for one release is the cheaper half of that
trade.

**On the warnings layout: adopted outright.** Fitting a new panel into a layout
that 0.5.1 replaces is exactly the time-sink described. Phase 6 now says so in as
many words: `warnings` renders as **a plain bulleted list or a toast, no layout
work**, and `otherStats` is returned and saved but **not displayed** until 0.5.1,
where it gets a proper surface alongside the three-tab rebuild.

*Landed:* Phase 6 (constrained scope), Phase 8 (`otherStats` and `warnings`
surfaces).

---

  ### 6. The withTimeout Trap (UI Doc §6)                                                                                                                    
                                                                                                                                                             
  • The Catch: Adding a timeout to Wails calls converts a silent hang into an error.                                                                         
  • The Miss: If the Wails bridge has actually dropped a message due to load, the bridge itself might be in a poisoned state. A timeout tells the user it    
  failed, but doesn't tell them how to recover.                                                                                                              
  • Recommendation: The error message caught by the timeout needs to be actionable. (e.g. "The calculation timed out and the connection may be unstable. Save
  your gearset and restart the app.") 

#### RESPONSE

**Verdict: adopted.** Correct, and cheap. A timeout fires *because* the bridge
dropped a message, and a bridge under enough load to drop one will likely drop
the next — so a bare "Request timed out" leaves the user in a state that recurs,
with no signal that restarting is the way out. `withTimeout` converts an
invisible hang into a visible one; without an actionable message that is only
half the value.

The message is now specified in Phase 8 rather than left to implementation:

> *"The calculation timed out and the app's connection may be unstable. Save your
> gearset and restart the app."*

It names the recovery and puts saving first, which matters because §3.4's rule —
never let a failed result overwrite saved stats — means the user's gearset is
still intact at that point and worth preserving before a restart.

*Landed:* Phase 8.
