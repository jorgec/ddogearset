<script lang="ts">
  // ItemDetail — the single place item information is rendered.
  //
  // Design constraints it exists to satisfy (docs/ITEM_DETAIL_SPEC.md):
  //   INV-1  Go hands us a verbatim structural projection of the XML. Nothing
  //          here re-implements python/optimizer.py's normalize_stat_name or
  //          DDO's bonus-type stacking rules — display parsing and solver
  //          matching are different jobs with deliberately different outputs.
  //   INV-4  itemName alone is enough. `slotDetail` is a pure enhancement; every
  //          section degrades to something useful without it.
  //   INV-5  Whether a buff actually counted comes from the real solve's output
  //          (`slotDetail`), never from us recomputing stacking rules.

  import { createEventDispatcher } from 'svelte';
  import { configStore, resultStore } from '$lib/store';
  import type { SlotBuff, SlotDetail } from '$lib/store';
  import { fetchItem, fetchSetBonus, fetchAugment } from '$lib/services/itemCatalog';
  import { GetAvailableAugments } from '../../../../wailsjs/go/main/App';
  import { BrowserOpenURL } from '../../../../wailsjs/runtime/runtime';
  import type { models } from '../../../../wailsjs/go/models';

  export let itemName: string;
  export let slot: string | null = null;
  /**
   * Per-slot detail from the last solve (`resultStore.slots[slot]`).
   *
   * Caller contract (EC-12): if you pass this, it must describe `itemName`. The
   * component deliberately does not validate the pairing — GearsetEditor always
   * derives both from the same slot, and a runtime check here would be
   * speculative guarding against a misuse that shouldn't occur.
   */
  export let slotDetail: SlotDetail | null = null;
  export let mode: 'view' | 'edit' = 'view';

  const dispatch = createEventDispatcher<{ minorArtifactToggle: { checked: boolean } }>();

  let item: models.XMLItem | null = null;
  let loading = false;
  let loadError = '';

  // Guards against a slow response for an item the user has already navigated
  // away from overwriting the current one (AC-19). Every fetch takes a token;
  // only the newest token is allowed to commit its result.
  let fetchToken = 0;

  // A click must never leave the panel spinning forever — cap the wait and
  // surface a clear error past this point instead. GetItemDetails itself is a
  // plain in-memory map lookup and returns instantly, but the caller (e.g. the
  // Owned Items screen) may hand us a name whose backing data is unusual, and
  // this is cheap insurance against any such case getting the user stuck.
  const LOAD_TIMEOUT_MS = 8000;

  $: void loadItem(itemName);

  async function loadItem(name: string) {
      if (!name) {
          item = null;
          return;
      }
      const token = ++fetchToken;
      loading = true;
      loadError = '';
      try {
          const timeout = new Promise<never>((_, reject) => {
              setTimeout(() => reject(new Error('timed out')), LOAD_TIMEOUT_MS);
          });
          const fetched = await Promise.race([fetchItem(name), timeout]);
          if (token !== fetchToken) return; // stale response — discard
          item = fetched && fetched.Name ? fetched : null;
          if (!item) loadError = `No data found for "${name}".`;
      } catch (e) {
          if (token !== fetchToken) return;
          item = null;
          loadError = e instanceof Error && e.message === 'timed out'
              ? `Timed out loading "${name}". It may not be a real catalog item.`
              : 'Could not load this item: ' + e;
      } finally {
          if (token === fetchToken) loading = false;
      }
  }

  // --- Stats & Buffs ------------------------------------------------------

  // A buff is visible to the solver only if it carries BOTH a value and a bonus
  // type — python/optimizer.py's parse_items requires `b_val and b_bonus` to
  // emit a buff tuple at all. This is a STATIC property of the buff and is
  // independent of the user's priorities (§6.4); roughly a quarter of all item
  // buffs in the corpus fail it by design.
  function usedByOptimizer(b: models.XMLBuff): boolean {
      return !!(b.Value1 && b.Value1.trim()) && !!(b.BonusType && b.BonusType.trim());
  }

  $: buffs = item?.Buffs ?? [];
  $: solverBuffs = buffs.filter(usedByOptimizer);
  $: displayOnlyBuffs = buffs.filter(b => !usedByOptimizer(b));

  // §7.3: Item is the more specific label when present (e.g. Type=AbilityBonus,
  // Item=Charisma), otherwise Type carries the whole name.
  function buffLabel(b: models.XMLBuff): string {
      return (b.Item && b.Item.trim()) || b.Type || '(unnamed)';
  }
  function buffQualifier(b: models.XMLBuff): string {
      return b.Item && b.Type && b.Item !== b.Type ? b.Type : '';
  }

  type Credit = 'counted' | 'superseded' | 'not-priority' | null;

  const VALUE_TOLERANCE = 1e-6;

  function sameStat(a: string, b: string): boolean {
      return !!a && !!b && a.trim().toLowerCase() === b.trim().toLowerCase();
  }

  /**
   * Cross-references one displayed buff against the buffs the solver actually
   * credited for this source in the last solve.
   *
   * Returns null when there is nothing to compare against — no slotDetail, or a
   * sub-array the current SlotDetail shape doesn't carry. That is the mandatory
   * graceful-degradation path (§6.2), not an error: `SlotDetail.item` has no
   * `buffs` field today, and this component must not depend on the in-flight
   * amendment that may add one.
   */
  function creditFor(b: models.XMLBuff, credited: SlotBuff[] | undefined | null): Credit {
      if (!credited) return null;
      // Match on either candidate stat name. The solver's `stat` is normalized
      // by Python; we do not replicate that normalization (INV-1), so a
      // non-match legitimately means "the solver never tracked this stat".
      const candidates = [buffLabel(b), b.Type, b.Item].filter(Boolean) as string[];
      const sameStatEntries = credited.filter(c => candidates.some(n => sameStat(n, c.stat)));
      if (sameStatEntries.length === 0) return 'not-priority';

      const value = Number(b.Value1);
      const exact = sameStatEntries.some(
          c => Number.isFinite(value) &&
               Math.abs(c.value - value) < VALUE_TOLERANCE &&
               sameStat(c.bonus, b.BonusType)
      );
      // The stat was tracked but this particular value/bonus-type pairing is not
      // what got credited — DDO counts only the best source of a non-stacking
      // bonus type, so another source won.
      return exact ? 'counted' : 'superseded';
  }

  const CREDIT_LABEL: Record<Exclude<Credit, null>, string> = {
      counted: 'counted',
      superseded: 'superseded by a higher source',
      'not-priority': 'not a priority',
  };
  const CREDIT_CLASS: Record<Exclude<Credit, null>, string> = {
      counted: 'bg-primary/15 text-primary border-primary/30',
      superseded: 'bg-amber-500/15 text-amber-500 border-amber-500/30',
      'not-priority': 'bg-muted text-muted-foreground border-border',
  };

  // SlotDetail.item has no `buffs` field in the current shape — see §6.2.
  $: itemCreditBuffs = (slotDetail?.item as any)?.buffs as SlotBuff[] | undefined;

  function augmentCreditBuffs(name: string | null): SlotBuff[] | undefined {
      if (!name) return undefined;
      return slotDetail?.augments?.find(a => a.name === name)?.buffs;
  }
  function setCreditBuffs(setName: string): SlotBuff[] | undefined {
      return slotDetail?.set_bonus_contributions?.find(s => s.set === setName)?.buffs;
  }

  // --- Weapon profile -----------------------------------------------------

  $: baseDiceText = item?.BaseDice && (item.BaseDice.Number || item.BaseDice.Sides)
      ? `${item.BaseDice.Number}d${item.BaseDice.Sides}`
      : '';

  // Expected value of the dice, framed the same way the solver's
  // "base damage dice" stat is (docs/PHASE10_PLAN.md §15.3), so the two agree
  // on what the number means even though this panel makes no solver call.
  $: baseDiceExpected = (() => {
      const n = Number(item?.BaseDice?.Number);
      const s = Number(item?.BaseDice?.Sides);
      if (!Number.isFinite(n) || !Number.isFinite(s) || n <= 0 || s <= 0) return '';
      return (n * (s + 1) / 2).toFixed(1);
  })();

  // Conventional DDO notation. NOTE: the spec writes this as
  // `20 - CriticalThreatRange`, which is off by one — a threat range of 3 means
  // 3 numbers crit (18, 19, 20), so the low end is 21 - range. Rendering 17-20
  // for a rapier would be visibly wrong in-game, so this uses 21 - range and the
  // deviation is recorded here deliberately.
  $: criticalProfile = (() => {
      const mult = item?.CriticalMultiplier ?? '';
      const range = item?.CriticalThreatRange ?? '';
      const r = Number(range);
      const m = Number(mult);
      if (Number.isFinite(r) && r > 0 && Number.isFinite(m) && m > 0) {
          const low = 21 - r;
          return `${low}-20 ×${m}`;
      }
      // Never blank: fall back to whichever raw field we do have.
      const parts: string[] = [];
      if (range) parts.push(`threat range ${range}`);
      if (mult) parts.push(`multiplier ×${mult}`);
      return parts.join(', ');
  })();

  // --- Augment slots ------------------------------------------------------

  let editingAugmentSlotIdx: number | null = null;
  let availableAugments: models.XMLAugment[] = [];
  let isFetchingAugments = false;
  let augmentSearchQuery = '';
  let augmentSearchTimeout: any;

  // Full detail for socketed augments, resolved lazily and only when slotDetail
  // didn't already hand us solver-credited buffs for them (§7.6, path 2).
  // `requestedAugments` is intentionally not reactive — it only stops the
  // reactive block below from firing the same fetch twice.
  let socketedAugmentDetail: Record<string, models.XMLAugment | null> = {};
  const requestedAugments = new Set<string>();

  function getAugmentOccurrenceIndex(idx: number, color: string): number {
      if (!item) return 0;
      let count = 0;
      for (let i = 0; i < idx; i++) {
          if (item.ItemAugments[i].Type === color) count++;
      }
      return count;
  }

  function getAugmentName(idx: number, color: string): string | null {
      if (!slot || !$configStore.pre_filled_augments?.[slot]) return null;
      const val = ($configStore.pre_filled_augments as any)[slot][color];
      if (!val) return null;
      const occ = getAugmentOccurrenceIndex(idx, color);
      if (Array.isArray(val)) return val[occ] || null;
      return occ === 0 ? val : null;
  }

  // Resolve detail for anything socketed that slotDetail can't explain.
  // ItemAugments is `null` (not `[]`) whenever an item has zero augment
  // slots — Go's encoding/json emits nil slices that way — so this must not
  // assume an array. Skipping the guard here previously threw mid-render for
  // any augment-less item (starter gear, Anger's Gift, etc.), which looked
  // like the drawer being permanently stuck on "Loading item…" even though
  // GetItemDetails had already returned successfully.
  $: if (item) {
      (item.ItemAugments ?? []).forEach((aug, idx) => {
          const name = getAugmentName(idx, aug.Type);
          if (name && !requestedAugments.has(name) && !augmentCreditBuffs(name)) {
              requestedAugments.add(name);
              fetchAugment(name).then(detail => {
                  socketedAugmentDetail = { ...socketedAugmentDetail, [name]: detail };
              });
          }
      });
  }

  async function openAugmentPicker(idx: number, type: string) {
      editingAugmentSlotIdx = idx;
      augmentSearchQuery = '';
      await fetchAugments(type, '');
  }

  async function fetchAugments(type: string, query: string) {
      isFetchingAugments = true;
      try {
          availableAugments = (await GetAvailableAugments(type, $configStore.max_level || 34, query)) || [];
      } catch (e) {
          console.error(e);
      } finally {
          isFetchingAugments = false;
      }
  }

  function handleAugmentSearchInput(type: string) {
      clearTimeout(augmentSearchTimeout);
      augmentSearchTimeout = setTimeout(() => fetchAugments(type, augmentSearchQuery), 300);
  }

  function selectAugment(idx: number, color: string, aug: models.XMLAugment) {
      if (!slot) return;
      if (!$configStore.pre_filled_augments[slot]) {
          $configStore.pre_filled_augments[slot] = {};
      }
      const bucket = ($configStore.pre_filled_augments as any)[slot];
      const occ = getAugmentOccurrenceIndex(idx, color);
      const existing = bucket[color];

      if (Array.isArray(existing)) {
          existing[occ] = aug.Name;
          bucket[color] = existing;
      } else if (existing && occ > 0) {
          const arr = [existing];
          arr[occ] = aug.Name;
          bucket[color] = arr;
      } else if (occ > 0) {
          const arr: string[] = [];
          arr[occ] = aug.Name;
          bucket[color] = arr;
      } else {
          bucket[color] = aug.Name;
      }

      $configStore.pre_filled_augments = { ...$configStore.pre_filled_augments };
      editingAugmentSlotIdx = null;
  }

  function clearAugment(idx: number, color: string) {
      if (!slot || !$configStore.pre_filled_augments?.[slot]) return;
      const bucket = ($configStore.pre_filled_augments as any)[slot];
      const occ = getAugmentOccurrenceIndex(idx, color);
      const existing = bucket[color];
      if (Array.isArray(existing)) {
          existing[occ] = ''; // keep array length so later occurrences don't shift
          bucket[color] = existing;
      } else if (occ === 0) {
          delete bucket[color];
      }
      $configStore.pre_filled_augments = { ...$configStore.pre_filled_augments };
  }

  // --- Set bonuses --------------------------------------------------------

  interface SetRef {
      name: string;
      /** Non-empty when membership is granted only by choosing a specific upgrade. */
      viaAugment: string;
  }

  // Unconditional membership comes from the item's own top-level <SetBonus>.
  // Conditional membership is nested under <ItemAugment><Augment> — the game
  // grants it only if that upgrade is chosen, so it is labelled as such and
  // excluded from the live piece count unless we can confirm it is selected.
  $: setRefs = (() => {
      const refs: SetRef[] = [];
      const seen = new Set<string>();
      for (const name of item?.SetBonuses ?? []) {
          if (name && !seen.has(name)) { seen.add(name); refs.push({ name, viaAugment: '' }); }
      }
      for (const ia of item?.ItemAugments ?? []) {
          for (const emb of ia.Augments ?? []) {
              if (emb.SetBonus && !seen.has(emb.SetBonus)) {
                  seen.add(emb.SetBonus);
                  refs.push({ name: emb.SetBonus, viaAugment: emb.Name || ia.Type });
              }
          }
      }
      return refs;
  })();

  // undefined = still loading, null = the backend has no such set (its
  // zero-value/not-found contract), otherwise the resolved detail.
  let setDetail: Record<string, models.XMLSetBonus | null> = {};
  const requestedSets = new Set<string>();
  $: for (const ref of setRefs) {
      if (!requestedSets.has(ref.name)) {
          requestedSets.add(ref.name);
          fetchSetBonus(ref.name).then(d => { setDetail = { ...setDetail, [ref.name]: d }; });
      }
  }

  /**
   * How many pieces of this set the last solve had equipped.
   *
   * Read straight out of the solve's own `set_bonus_contributions` rather than
   * recounted here — the solver already emits this per slot and re-deriving it
   * would be exactly the kind of duplicated rule INV-5 forbids. Returns null
   * when there is no solve to read.
   */
  function equippedPieces(setName: string): number | null {
      const slots = ($resultStore as any)?.slots as Record<string, SlotDetail> | undefined;
      if (!slots) return null;
      for (const detail of Object.values(slots)) {
          const hit = detail?.set_bonus_contributions?.find(s => s.set === setName);
          if (hit) return hit.pieces;
      }
      return null;
  }

  function maxTierCount(set: models.XMLSetBonus | null): number | null {
      if (!set?.Tiers?.length) return null;
      const counts = set.Tiers.map(t => Number(t.EquippedCount)).filter(n => Number.isFinite(n));
      return counts.length ? Math.max(...counts) : null;
  }

  /** A conditional set only counts once we can confirm its upgrade is chosen. */
  function conditionalIsSelected(ref: SetRef): boolean {
      if (!ref.viaAugment) return true;
      if (!item) return false;
      return (item.ItemAugments ?? []).some((ia, idx) =>
          ia.SelectedAugment === ref.viaAugment || getAugmentName(idx, ia.Type) === ref.viaAugment
      );
  }

  // --- Effects ------------------------------------------------------------

  function effectSummary(e: models.XMLEffect): string {
      const parts: string[] = [];
      if (e.Types?.length) parts.push(e.Types.join(' + '));
      if (e.Amount) parts.push(e.Amount);
      if (e.Bonus) parts.push(`(${e.Bonus})`);
      return parts.join(' ') || '(no details)';
  }

  // --- Acquisition --------------------------------------------------------

  // "base" is enrichment.go's default when no pack keyword matched.
  $: packLabel = !item?.pack_id ? '' : item.pack_id === 'base' ? 'Base Game' : item.pack_id;

  // --- Header -------------------------------------------------------------

  // Deliberately the existing frontend-side direct page link, NOT the backend's
  // wiki_url (which is a Special:Search link). Changing link targets silently
  // is not in scope; the backend field is shown under Acquisition instead.
  function openWiki(name: string) {
      BrowserOpenURL(`https://ddowiki.com/page/Item:${name.replace(/ /g, '_')}`);
  }

  $: slotNames = (item?.EquipmentSlot?.Slots ?? []).map((s: any) => s?.Local ?? s).filter(Boolean);
  $: isMinorArtifact = !!item && item.MinorArtifact !== undefined && item.MinorArtifact !== null;
</script>

{#if loading && !item}
  <p class="text-muted-foreground animate-pulse">Loading item…</p>
{:else if !item}
  <p class="text-muted-foreground italic">{loadError || 'No item selected.'}</p>
{:else}
  <div class="space-y-4">
    <!-- ============ Header (always visible, never collapsible) ============ -->
    <div class="space-y-3">
      <div class="flex items-start justify-between gap-4">
        <div>
          <h3 class="text-2xl font-bold tracking-tight">{item.Name}</h3>
          <p class="text-sm text-muted-foreground mt-1">
            ML: {item.MinLevel}
            {#if slotNames.length}
              &middot; {slotNames.join(', ')}
            {/if}
          </p>
        </div>
        {#if mode === 'edit' && slot}
          <label class="flex items-center space-x-2 text-sm cursor-pointer border border-border p-2 rounded hover:bg-muted/50 transition-colors shrink-0">
            <input
              type="checkbox"
              checked={isMinorArtifact}
              on:change={(e) => dispatch('minorArtifactToggle', { checked: e.currentTarget.checked })}
              class="rounded border-input text-primary focus:ring-primary"
            />
            <span>Is Minor Artifact?</span>
          </label>
        {/if}
      </div>

      <div class="flex space-x-3">
        <button on:click={() => openWiki(item.Name)} class="inline-flex items-center justify-center rounded-md text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 h-9 px-4 py-2 cursor-pointer transition-colors">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="mr-2"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>
          DDO Wiki
        </button>
      </div>
    </div>

    <!-- ==================== Stats & Buffs ==================== -->
    {#if buffs.length === 0}
      <p class="text-sm text-muted-foreground italic">No buffs on this item.</p>
    {:else}
      <details open class="border border-border/50 rounded">
        <summary class="cursor-pointer px-3 py-2 font-semibold select-none">
          Stats &amp; Buffs
          <span class="text-xs font-normal text-muted-foreground">({buffs.length})</span>
        </summary>
        <div class="px-3 pb-3 space-y-4">
          {#if solverBuffs.length}
            <div>
              <h5 class="text-xs uppercase tracking-wide text-muted-foreground mb-1">Used by the optimizer</h5>
              <table class="w-full text-sm">
                <tbody>
                  {#each solverBuffs as b}
                    {@const credit = creditFor(b, itemCreditBuffs)}
                    <tr class="border-t border-border/30 align-top">
                      <td class="py-1 pr-2">
                        <span class="font-medium">{buffLabel(b)}</span>
                        {#if buffQualifier(b)}
                          <span class="text-xs text-muted-foreground ml-1">{buffQualifier(b)}</span>
                        {/if}
                        {#if b.Description1 && b.Description1 !== b.Item}
                          <div class="text-xs text-muted-foreground">{b.Description1}</div>
                        {/if}
                      </td>
                      <td class="py-1 pr-2 font-mono whitespace-nowrap">
                        {b.Value1}{#if b.Value2}<span class="text-muted-foreground"> / {b.Value2}</span>{/if}
                      </td>
                      <td class="py-1 pr-2 text-xs text-muted-foreground whitespace-nowrap">{b.BonusType}</td>
                      <td class="py-1 text-right">
                        {#if credit}
                          <span class="text-[10px] px-1.5 py-0.5 rounded border {CREDIT_CLASS[credit]}">{CREDIT_LABEL[credit]}</span>
                        {/if}
                      </td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {/if}

          {#if displayOnlyBuffs.length}
            <div class="opacity-60">
              <h5 class="text-xs uppercase tracking-wide text-muted-foreground mb-1">
                Not used by the optimizer
              </h5>
              <p class="text-[11px] text-muted-foreground mb-1">
                These have no value and/or no bonus type in the game data, so the solver cannot score them.
                They still apply in game.
              </p>
              <table class="w-full text-sm">
                <tbody>
                  {#each displayOnlyBuffs as b}
                    <tr class="border-t border-border/30 align-top">
                      <td class="py-1 pr-2">
                        <span>{buffLabel(b)}</span>
                        {#if buffQualifier(b)}
                          <span class="text-xs text-muted-foreground ml-1">{buffQualifier(b)}</span>
                        {/if}
                        {#if b.Description1 && b.Description1 !== b.Item}
                          <div class="text-xs text-muted-foreground">{b.Description1}</div>
                        {/if}
                      </td>
                      <td class="py-1 pr-2 font-mono whitespace-nowrap">{b.Value1 || ''}</td>
                      <td class="py-1 text-xs text-muted-foreground whitespace-nowrap">{b.BonusType || ''}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {/if}
        </div>
      </details>
    {/if}

    <!-- ==================== Weapon Profile ==================== -->
    {#if item.Weapon}
      <details class="border border-border/50 rounded">
        <summary class="cursor-pointer px-3 py-2 font-semibold select-none">Weapon Profile</summary>
        <dl class="px-3 pb-3 text-sm grid grid-cols-[auto,1fr] gap-x-4 gap-y-1">
          <dt class="text-muted-foreground">Type</dt><dd>{item.Weapon}</dd>
          {#if item.AttackModifier}
            <dt class="text-muted-foreground">Attack</dt><dd>{item.AttackModifier}</dd>
          {/if}
          {#if item.DamageModifier}
            <dt class="text-muted-foreground">Damage</dt><dd>{item.DamageModifier}</dd>
          {/if}
          {#if baseDiceText}
            <dt class="text-muted-foreground">Base dice</dt>
            <dd>{baseDiceText}{#if baseDiceExpected}<span class="text-muted-foreground"> (avg {baseDiceExpected})</span>{/if}</dd>
          {/if}
          {#if item.WeaponDamage}
            <dt class="text-muted-foreground">Weapon damage</dt><dd>[W] {item.WeaponDamage}</dd>
          {/if}
          {#if criticalProfile}
            <dt class="text-muted-foreground">Critical</dt><dd>{criticalProfile}</dd>
          {/if}
          {#if item.DRBypass?.length}
            <dt class="text-muted-foreground">DR bypass</dt><dd>{item.DRBypass.join(', ')}</dd>
          {/if}
          {#if item.Material}
            <dt class="text-muted-foreground">Material</dt><dd>{item.Material}</dd>
          {/if}
        </dl>
      </details>
    {/if}

    <!-- ==================== Armor Profile ==================== -->
    {#if item.Armor}
      <details class="border border-border/50 rounded">
        <summary class="cursor-pointer px-3 py-2 font-semibold select-none">Armor Profile</summary>
        <dl class="px-3 pb-3 text-sm grid grid-cols-[auto,1fr] gap-x-4 gap-y-1">
          <dt class="text-muted-foreground">Type</dt><dd>{item.Armor}</dd>
          {#if item.ArmorBonus}
            <dt class="text-muted-foreground">Armor bonus</dt><dd>{item.ArmorBonus}</dd>
          {/if}
          {#if item.ShieldBonus}
            <dt class="text-muted-foreground">Shield bonus</dt><dd>{item.ShieldBonus}</dd>
          {/if}
          {#if item.MaximumDexterityBonus}
            <dt class="text-muted-foreground">Max Dex bonus</dt><dd>{item.MaximumDexterityBonus}</dd>
          {/if}
          {#if item.ArcaneSpellFailure}
            <dt class="text-muted-foreground">Arcane spell failure</dt><dd>{item.ArcaneSpellFailure}%</dd>
          {/if}
          {#if item.ArmorCheckPenalty}
            <dt class="text-muted-foreground">Armor check penalty</dt><dd>{item.ArmorCheckPenalty}</dd>
          {/if}
        </dl>
      </details>
    {/if}

    <!-- ==================== Augment Slots ==================== -->
    {#if item.ItemAugments?.length}
      <details class="border border-border/50 rounded">
        <summary class="cursor-pointer px-3 py-2 font-semibold select-none">
          Augment Slots <span class="text-xs font-normal text-muted-foreground">({item.ItemAugments.length})</span>
        </summary>
        <div class="px-3 pb-3 space-y-3">
          {#each item.ItemAugments as aug, idx}
            {@const socketed = getAugmentName(idx, aug.Type)}
            <div class="flex flex-col space-y-1">
              <div class="flex justify-between items-center text-sm font-medium">
                <span>{aug.Type} Slot</span>
                {#if socketed && mode === 'edit' && slot}
                  <button class="text-xs text-destructive hover:underline" on:click={() => clearAugment(idx, aug.Type)}>Remove</button>
                {/if}
              </div>

              {#if aug.SelectedAugment}
                <!-- Informational only: what the item ships with. Never overrides
                     whatever the user has actually socketed (EC-7). -->
                <p class="text-xs text-muted-foreground">Ships with: {aug.SelectedAugment}</p>
              {/if}

              {#if mode === 'edit' && slot && editingAugmentSlotIdx === idx}
                <div class="mt-2 p-3 bg-muted/30 rounded border border-border">
                  <div class="flex justify-between items-center mb-2">
                    <input type="text" bind:value={augmentSearchQuery} on:input={() => handleAugmentSearchInput(aug.Type)} placeholder="Search {aug.Type} augments..." class="flex-1 h-8 rounded-md border border-input bg-background px-2 text-xs mr-2" />
                    <button class="text-xs text-muted-foreground hover:text-primary" on:click={() => editingAugmentSlotIdx = null}>Cancel</button>
                  </div>
                  <div class="max-h-40 overflow-y-auto space-y-1">
                    {#if isFetchingAugments}
                      <p class="text-xs text-muted-foreground animate-pulse">Loading...</p>
                    {:else}
                      {#each availableAugments as availableAug}
                        <button on:click={() => selectAugment(idx, aug.Type, availableAug)} class="w-full text-left p-2 rounded text-xs bg-card hover:bg-muted transition-colors border border-transparent hover:border-primary">
                          <div class="font-semibold">{availableAug.Name}</div>
                          <div class="text-[10px] text-muted-foreground truncate">{availableAug.Description} (ML: {availableAug.MinLevel})</div>
                        </button>
                      {/each}
                      {#if availableAugments.length === 0}
                        <p class="text-xs text-muted-foreground">No matching augments found.</p>
                      {/if}
                    {/if}
                  </div>
                </div>
              {:else if mode === 'edit' && slot}
                <button on:click={() => openAugmentPicker(idx, aug.Type)} class="w-full text-left p-2 rounded bg-muted/50 hover:bg-muted border border-transparent hover:border-primary transition-colors text-sm">
                  {#if socketed}
                    <span class="text-primary font-medium">{socketed}</span>
                  {:else}
                    <span class="text-muted-foreground italic">Empty (Click to add)</span>
                  {/if}
                </button>
              {:else}
                <div class="p-2 rounded bg-muted/30 text-sm">
                  {#if socketed}
                    <span class="text-primary font-medium">{socketed}</span>
                  {:else}
                    <span class="text-muted-foreground italic">Empty</span>
                  {/if}
                </div>
              {/if}

              <!-- Socketed augment detail: solver-credited buffs when the last
                   solve knows about it, otherwise the catalog's own effects. -->
              {#if socketed}
                {@const credited = augmentCreditBuffs(socketed)}
                {#if credited?.length}
                  <ul class="text-xs text-muted-foreground pl-3 list-disc">
                    {#each credited as cb}
                      <li>{cb.stat} {cb.value} <span class="opacity-70">({cb.bonus})</span></li>
                    {/each}
                  </ul>
                {:else if socketedAugmentDetail[socketed]?.Description}
                  <p class="text-xs text-muted-foreground pl-1">{socketedAugmentDetail[socketed]?.Description}</p>
                {/if}
              {/if}

              <!-- Embedded upgrade/crafting choices for this slot. -->
              {#if aug.Augments?.length}
                <div class="pl-3 border-l border-border/50 space-y-1">
                  <p class="text-xs uppercase tracking-wide text-muted-foreground">Upgrade choices</p>
                  {#each aug.Augments as emb}
                    <div class="text-xs">
                      <span class="font-medium">{emb.Name}</span>
                      {#if emb.MinLevel}<span class="text-muted-foreground"> (ML: {emb.MinLevel})</span>{/if}
                      {#if emb.Description}
                        <div class="text-muted-foreground">{emb.Description}</div>
                      {/if}
                      {#if emb.SetBonus}
                        <div class="text-amber-500">
                          Grants the "{emb.SetBonus}" set &mdash; conditional, requires the "{emb.Name}" upgrade
                        </div>
                      {/if}
                    </div>
                  {/each}
                </div>
              {/if}
            </div>
          {/each}
        </div>
      </details>
    {/if}

    <!-- ==================== Set Bonuses ==================== -->
    {#if setRefs.length}
      <details class="border border-border/50 rounded">
        <summary class="cursor-pointer px-3 py-2 font-semibold select-none">
          Set Bonuses <span class="text-xs font-normal text-muted-foreground">({setRefs.length})</span>
        </summary>
        <div class="px-3 pb-3 space-y-4">
          {#each setRefs as ref}
            {@const detail = setDetail[ref.name]}
            {@const pieces = ref.viaAugment && !conditionalIsSelected(ref) ? null : equippedPieces(ref.name)}
            {@const maxCount = maxTierCount(detail)}
            <div>
              <div class="flex items-baseline justify-between gap-2">
                <h5 class="font-medium">{ref.name}</h5>
                {#if pieces !== null && maxCount !== null}
                  <span class="text-xs text-muted-foreground">{pieces}/{maxCount} pieces equipped</span>
                {/if}
              </div>
              {#if ref.viaAugment}
                <p class="text-xs text-amber-500">
                  Conditional &mdash; requires the "{ref.viaAugment}" upgrade
                  {#if !conditionalIsSelected(ref)}(not currently selected){/if}
                </p>
              {/if}
              {#if detail === undefined}
                <p class="text-xs text-muted-foreground italic animate-pulse">Loading set details…</p>
              {:else if detail === null}
                <p class="text-xs text-muted-foreground italic">Set details unavailable.</p>
              {:else}
                <ul class="mt-1 space-y-2">
                  {#each detail.Tiers ?? [] as tier}
                    <li class="text-sm">
                      <span class="font-mono text-xs text-muted-foreground">{tier.EquippedCount} pieces:</span>
                      {tier.Description}
                      {#if tier.Effects?.length}
                        <ul class="text-xs text-muted-foreground pl-4 list-disc">
                          {#each tier.Effects as eff}
                            <li>{effectSummary(eff)}</li>
                          {/each}
                        </ul>
                      {/if}
                    </li>
                  {/each}
                </ul>
              {/if}
              {#if setCreditBuffs(ref.name)?.length}
                <p class="text-[11px] text-primary mt-1">Counted in the last solve.</p>
              {/if}
            </div>
          {/each}
        </div>
      </details>
    {/if}

    <!-- ==================== Clickies & Effects ==================== -->
    {#if item.Effects?.length}
      <details class="border border-border/50 rounded">
        <summary class="cursor-pointer px-3 py-2 font-semibold select-none">
          Clickies &amp; Effects <span class="text-xs font-normal text-muted-foreground">({item.Effects.length})</span>
        </summary>
        <ul class="px-3 pb-3 space-y-2 text-sm">
          {#each item.Effects as eff}
            <li>
              <span class="font-medium">{eff.Types?.join(' + ') || '(effect)'}</span>
              {#if eff.Amount}<span class="font-mono ml-1">{eff.Amount}</span>{/if}
              {#if eff.Bonus}<span class="text-xs text-muted-foreground ml-1">({eff.Bonus})</span>{/if}
              {#if eff.Item}<div class="text-xs text-muted-foreground">Applies to: {eff.Item}</div>{/if}
              {#each eff.Requirements ?? [] as req}
                <div class="text-xs text-muted-foreground">Requires: {req.Type} {req.Item}</div>
              {/each}
            </li>
          {/each}
        </ul>
      </details>
    {/if}

    <!-- ==================== Acquisition ==================== -->
    {#if item.DropLocations?.length || packLabel}
      <details class="border border-border/50 rounded">
        <summary class="cursor-pointer px-3 py-2 font-semibold select-none">Acquisition</summary>
        <div class="px-3 pb-3 text-sm space-y-2">
          {#if packLabel}
            <div><span class="text-muted-foreground">Pack:</span> {packLabel}</div>
          {/if}
          {#if item.DropLocations?.length}
            <div>
              <span class="text-muted-foreground">Drop locations:</span>
              <ul class="list-disc pl-5">
                {#each item.DropLocations as loc}
                  <li class="whitespace-pre-line">{loc}</li>
                {/each}
              </ul>
            </div>
          {:else}
            <div class="text-muted-foreground italic">Drop location unknown.</div>
          {/if}
          <!-- docs/RAID_DETECTION_SPEC.md — real, populated raid detection
               (direct DropLocation match or an upgrade/crafting chain
               tracing back to a raid item). Say nothing when false rather
               than asserting the unverified "not a raid" (a raid item whose
               chain this app's two signals don't happen to catch would
               otherwise render a false negative badge). -->
          {#if item.is_raid}
            <div>
              <span class="inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium bg-amber-500/20 text-amber-400 border border-amber-500/30">
                Raid Item{item.raid_name ? `: ${item.raid_name}` : ''}
              </span>
            </div>
          {/if}
        </div>
      </details>
    {/if}

    <!-- ==================== Raw Description ==================== -->
    {#if item.Description}
      <details class="border border-border/50 rounded">
        <summary class="cursor-pointer px-3 py-2 font-semibold select-none">Raw Description</summary>
        <div class="px-3 pb-3 prose prose-sm dark:prose-invert max-w-none">
          {@html item.Description}
        </div>
      </details>
    {/if}
  </div>
{/if}
