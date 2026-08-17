<script lang="ts">
  // Five tier lanes (docs/TIERED_SOLVER_FRONTEND_SPEC.md §3).
  //
  // Lanes rather than a tier dropdown per row because the model has two
  // orthogonal dimensions — tier, and intra-tier rank via array order — and a
  // flat list with a <select> renders only one of them visibly. Which lane a
  // chip is in = its tier; its position in the lane = its rank. This is also
  // what delivers INV-1 structurally: a chip is one node with one parent, so it
  // cannot exist in two tiers at once and the duplicate-across-tiers payload
  // the solver rejects is simply unconstructable here.

  import { configStore, resultStore, showToast, statSetUndoSnapshot, highlightedStats } from '$lib/store';
  import StatPicker from './StatPicker.svelte';
  import {
      TIERS,
      TIER_META,
      canAddStat,
      cloneLanes,
      findTier,
      hydrateLanes,
      isValidCap,
      serializePriorities,
      CAP_ERROR,
  } from '$lib/data/statPriorities';
  import type { Lanes, Tier } from '$lib/data/statPriorities';
  import { labelForStat, noteForStat } from '$lib/data/statTaxonomy';

  // Lanes are derived from the store rather than held as parallel state: the
  // store stays the single source of truth, and hydrate(serialize(x)) === x by
  // construction (§3.7), so a commit round-trips without drift or a loop.
  $: lanes = hydrateLanes($configStore.stat_priorities);

  let openPickerTier: Tier | null = null;
  let editingCapKey: string | null = null;
  let capDraft = '';

  // Post-solve feedback loop for the static taxonomy (§4.1): the solver tells
  // us which priorities matched nothing in the data files, and we badge the
  // still-placed chips rather than pretending to validate names up front.
  $: unmatched = new Set(
      ($resultStore?.unmatchedPriorities ?? []).map((s: string) => s.toLowerCase())
  );

  function commit(next: Lanes, { fromStatSet = false } = {}) {
      $configStore.stat_priorities = serializePriorities(next);
      // Any hand mutation invalidates the stat-set undo snapshot (§6.4).
      if (!fromStatSet) $statSetUndoSnapshot = null;
  }

  function addStat(tier: Tier, stat: string) {
      const trimmed = stat.trim();
      if (!trimmed) return;

      const existing = findTier(lanes, trimmed);
      if (existing) {
          showToast(
              `"${labelForStat(trimmed)}" is already in Tier ${existing}. Use "Move to tier" to change it.`,
              'info'
          );
          return;
      }

      const verdict = canAddStat(lanes, trimmed);
      if (!verdict.ok) {
          showToast(verdict.reason ?? 'That stat cannot be added.', 'error');
          return;
      }

      const next = cloneLanes(lanes);
      next[tier].push({ stat: trimmed });
      commit(next);
      openPickerTier = null;
  }

  function removeStat(tier: Tier, index: number) {
      const next = cloneLanes(lanes);
      next[tier].splice(index, 1);
      commit(next);
  }

  function move(tier: Tier, index: number, direction: 'up' | 'down') {
      const target = direction === 'up' ? index - 1 : index + 1;
      if (target < 0 || target >= lanes[tier].length) return;
      const next = cloneLanes(lanes);
      [next[tier][index], next[tier][target]] = [next[tier][target], next[tier][index]];
      commit(next);
  }

  function moveToTier(fromTier: Tier, index: number, toTier: Tier) {
      if (fromTier === toTier) return;
      const next = cloneLanes(lanes);
      const [chip] = next[fromTier].splice(index, 1);
      next[toTier].push(chip);
      commit(next);
  }

  function capKey(tier: Tier, index: number) {
      return `${tier}:${index}`;
  }

  function startCapEdit(tier: Tier, index: number) {
      editingCapKey = capKey(tier, index);
      capDraft = lanes[tier][index].cap ? String(lanes[tier][index].cap) : '';
  }

  // Cancelable inline edit, not a live binding (EC-9): dismissing without
  // submitting must leave the chip untouched.
  function cancelCapEdit() {
      editingCapKey = null;
      capDraft = '';
  }

  function commitCapEdit(tier: Tier, index: number) {
      const raw = capDraft.trim();
      const next = cloneLanes(lanes);

      if (raw === '') {
          delete next[tier][index].cap;
          commit(next);
          cancelCapEdit();
          return;
      }

      // Wording matches the server-side message verbatim so the two can never
      // disagree about the same rule.
      if (!isValidCap(raw)) {
          showToast(CAP_ERROR, 'error');
          return;
      }

      next[tier][index].cap = parseInt(raw, 10);
      commit(next);
      cancelCapEdit();
  }

  function handleCapKeydown(e: KeyboardEvent, tier: Tier, index: number) {
      if (e.key === 'Enter') {
          e.preventDefault();
          commitCapEdit(tier, index);
      } else if (e.key === 'Escape') {
          e.preventDefault();
          cancelCapEdit();
      }
  }

  // Svelte 3's template parser rejects TS casts inside markup expressions, so
  // the <select> handler unwraps its value here rather than inline.
  function onTierSelect(e: Event, fromTier: Tier, index: number) {
      const value = parseInt((e.target as HTMLSelectElement).value, 10) as Tier;
      moveToTier(fromTier, index, value);
  }

  function togglePicker(tier: Tier) {
      openPickerTier = openPickerTier === tier ? null : tier;
  }
</script>

<div class="space-y-4">
  <p class="text-xs text-muted-foreground">
    Drop each stat into the tier that matches how much you care about it. Within a lane, higher
    up means higher priority.
  </p>

  {#each TIERS as tier (tier)}
    <div class="rounded-lg border border-border bg-card/20 p-3 space-y-2">
      <div class="flex items-baseline justify-between gap-2">
        <div class="min-w-0">
          <h4 class="text-sm font-semibold">
            <span class="text-muted-foreground mr-1">Tier {tier}</span>{TIER_META[tier].header}
          </h4>
          <p class="text-[11px] text-muted-foreground">{TIER_META[tier].sub}</p>
          {#if tier === 1}
            <!-- Replaces the deleted computeFiligreeBias() readout (§7.1): the
                 honest, actionable version of what that percentage gestured at. -->
            <p class="text-[11px] text-primary/80 mt-0.5">
              Filigrees are only counted toward Tier 1. Tiers 2–5 are optimized from items,
              augments and set bonuses only.
            </p>
          {/if}
        </div>

        <div class="shrink-0">
          <button
            type="button"
            class="rounded-md border border-border bg-secondary text-secondary-foreground px-2 py-1 text-xs hover:bg-secondary/80 transition-colors"
            on:click={() => togglePicker(tier)}
          >Add stat ▾</button>
        </div>
      </div>

      {#if lanes[tier].length === 0}
        <div class="rounded border border-dashed border-border/70 px-3 py-2 text-[11px] text-muted-foreground">
          No solve stage runs for an empty tier
        </div>
      {:else}
        <div class="space-y-1.5">
          {#each lanes[tier] as chip, i (chip.stat)}
            <div
              class="rounded-md border bg-card px-2 py-1.5 text-sm transition-colors {$highlightedStats.includes(chip.stat.toLowerCase()) ? 'border-primary ring-1 ring-primary' : 'border-border'}"
            >
              <div class="flex items-center gap-2">
                <div class="flex flex-col space-y-0.5">
                  <button
                    type="button"
                    class="text-[10px] leading-none hover:text-primary disabled:opacity-30"
                    on:click={() => move(tier, i, 'up')}
                    disabled={i === 0}
                    aria-label="Move up">▲</button>
                  <button
                    type="button"
                    class="text-[10px] leading-none hover:text-primary disabled:opacity-30"
                    on:click={() => move(tier, i, 'down')}
                    disabled={i === lanes[tier].length - 1}
                    aria-label="Move down">▼</button>
                </div>

                <span class="font-medium truncate" title={chip.stat}>{labelForStat(chip.stat)}</span>

                {#if unmatched.has(chip.stat.toLowerCase())}
                  <span
                    class="shrink-0 rounded bg-destructive/20 text-destructive px-1.5 py-0.5 text-[10px] font-semibold"
                    title="The last solve found no sources for this stat in the data files."
                  >no matches</span>
                {/if}

                <div class="ml-auto flex items-center gap-2 shrink-0">
                  {#if editingCapKey === capKey(tier, i)}
                    <input
                      type="text"
                      bind:value={capDraft}
                      on:keydown={(e) => handleCapKeydown(e, tier, i)}
                      on:blur={cancelCapEdit}
                      placeholder="cap"
                      class="h-6 w-16 rounded border border-input bg-transparent px-1 text-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    />
                  {:else}
                    <button
                      type="button"
                      class="rounded border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground hover:text-foreground hover:border-primary transition-colors"
                      on:click={() => startCapEdit(tier, i)}
                      title="Stop rewarding this stat past a value"
                    >{chip.cap ? `cap ${chip.cap}` : '+ cap'}</button>
                  {/if}

                  <select
                    class="h-6 rounded border border-input bg-transparent text-[10px] px-1 focus-visible:outline-none"
                    value={tier}
                    on:change={(e) => onTierSelect(e, tier, i)}
                    aria-label="Move to tier"
                  >
                    {#each TIERS as t}
                      <option value={t} disabled={t === tier} class="bg-background text-foreground">
                        Tier {t}
                      </option>
                    {/each}
                  </select>

                  <button
                    type="button"
                    class="text-destructive hover:text-destructive/80 font-bold"
                    on:click={() => removeStat(tier, i)}
                    aria-label="Remove">&times;</button>
                </div>
              </div>

              <!-- EC-3: the caveat stays visible for as long as the chip does,
                   not only at selection time in the picker. -->
              {#if noteForStat(chip.stat)}
                <p class="mt-1 pl-6 text-[10px] text-muted-foreground italic">{noteForStat(chip.stat)}</p>
              {/if}
            </div>
          {/each}
        </div>
      {/if}
    </div>
  {/each}
</div>

{#if openPickerTier !== null}
  <StatPicker
    buildType={$configStore.build_type}
    on:select={(e) => { if (openPickerTier !== null) addStat(openPickerTier, e.detail); }}
    on:close={() => (openPickerTier = null)}
  />
{/if}
