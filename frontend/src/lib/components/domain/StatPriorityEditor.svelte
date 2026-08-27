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
      emptyLanes,
      findTier,
      hydrateLanes,
      isValidCap,
      serializePriorities,
      CAP_ERROR,
  } from '$lib/data/statPriorities';
  import type { Lanes, StatChip, Tier } from '$lib/data/statPriorities';
  import { labelForStat, noteForStat } from '$lib/data/statTaxonomy';
  import { dndzone } from 'svelte-dnd-action';
  import { flip } from 'svelte/animate';

  interface DndChip extends StatChip {
      id: string;
  }

  const FLIP_MS = 200;
  const DND_DROP_STYLE = {
      outline: '2px dashed hsl(var(--primary) / 0.4)',
      outlineOffset: '2px',
  };

  $: lanes = hydrateLanes($configStore.stat_priorities);

  let dndItems: Record<Tier, DndChip[]> = { 1: [], 2: [], 3: [], 4: [], 5: [] };
  let dragging = false;

  // Sync dndItems from the store when not mid-drag. During drag, dndItems
  // diverges from lanes (consider events update visual state only); finalize
  // commits back to the store, which re-triggers this sync.
  $: if (!dragging) {
      dndItems = Object.fromEntries(
          TIERS.map(t => [t, lanes[t].map(c => ({ ...c, id: c.stat }))])
      ) as Record<Tier, DndChip[]>;
  }

  let openPickerTier: Tier | null = null;
  let editingCapKey: string | null = null;
  let capDraft = '';

  $: unmatched = new Set(
      ($resultStore?.unmatchedPriorities ?? []).map((s: string) => s.toLowerCase())
  );

  function commit(next: Lanes, { fromStatSet = false } = {}) {
      $configStore.stat_priorities = serializePriorities(next);
      if (!fromStatSet) $statSetUndoSnapshot = null;
  }

  function handleConsider(tier: Tier, e: CustomEvent<{items: DndChip[]}>) {
      dragging = true;
      dndItems[tier] = e.detail.items;
      dndItems = dndItems;
  }

  function handleFinalize(tier: Tier, e: CustomEvent<{items: DndChip[]}>) {
      dndItems[tier] = e.detail.items;
      dndItems = dndItems;
      const next = emptyLanes();
      for (const t of TIERS) {
          next[t] = dndItems[t].map(({ id, ...rest }) => rest);
      }
      commit(next);
      dragging = false;
  }

  function addStat(tier: Tier, stat: string) {
      const trimmed = stat.trim();
      if (!trimmed) return;

      const existing = findTier(lanes, trimmed);
      if (existing) {
          showToast(
              `"${labelForStat(trimmed)}" is already in Tier ${existing}. Drag it to change its tier.`,
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

  function removeStat(tier: Tier, stat: string) {
      const next = cloneLanes(lanes);
      const idx = next[tier].findIndex(c => c.stat === stat);
      if (idx >= 0) next[tier].splice(idx, 1);
      commit(next);
  }

  function capKey(tier: Tier, stat: string) {
      return `${tier}:${stat}`;
  }

  function startCapEdit(tier: Tier, chip: DndChip) {
      editingCapKey = capKey(tier, chip.id);
      capDraft = chip.cap ? String(chip.cap) : '';
  }

  function cancelCapEdit() {
      editingCapKey = null;
      capDraft = '';
  }

  function commitCapEdit(tier: Tier, stat: string) {
      const raw = capDraft.trim();
      const next = cloneLanes(lanes);
      const idx = next[tier].findIndex(c => c.stat === stat);
      if (idx < 0) { cancelCapEdit(); return; }

      if (raw === '') {
          delete next[tier][idx].cap;
          commit(next);
          cancelCapEdit();
          return;
      }

      if (!isValidCap(raw)) {
          showToast(CAP_ERROR, 'error');
          return;
      }

      next[tier][idx].cap = parseInt(raw, 10);
      commit(next);
      cancelCapEdit();
  }

  function handleCapKeydown(e: KeyboardEvent, tier: Tier, stat: string) {
      if (e.key === 'Enter') {
          e.preventDefault();
          commitCapEdit(tier, stat);
      } else if (e.key === 'Escape') {
          e.preventDefault();
          cancelCapEdit();
      }
  }

  function togglePicker(tier: Tier) {
      openPickerTier = openPickerTier === tier ? null : tier;
  }
</script>

<div class="space-y-4">
  <p class="text-xs text-muted-foreground">
    Drag stats between tiers or reorder within a tier. Higher up means higher priority.
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

      <div
        use:dndzone={{items: dndItems[tier], type: 'stat-chip', flipDurationMs: FLIP_MS, dropTargetStyle: DND_DROP_STYLE}}
        on:consider={(e) => handleConsider(tier, e)}
        on:finalize={(e) => handleFinalize(tier, e)}
        class="min-h-[2.5rem] space-y-1.5 rounded-md"
      >
        {#each dndItems[tier] as chip (chip.id)}
          <div
            animate:flip={{duration: FLIP_MS}}
            class="rounded-md border bg-card px-2 py-1.5 text-sm transition-colors touch-none
              {$highlightedStats.includes(chip.stat.toLowerCase()) ? 'border-primary ring-1 ring-primary' : 'border-border'}"
          >
            <div class="flex items-center gap-2">
              <span
                class="cursor-grab text-muted-foreground/50 hover:text-muted-foreground select-none text-xs leading-none"
                aria-label="Drag to reorder"
              >⠿</span>

              <span class="font-medium truncate" title={chip.stat}>{labelForStat(chip.stat)}</span>

              {#if unmatched.has(chip.stat.toLowerCase())}
                <span
                  class="shrink-0 rounded bg-destructive/20 text-destructive px-1.5 py-0.5 text-[10px] font-semibold"
                  title="The last solve found no sources for this stat in the data files."
                >no matches</span>
              {/if}

              <div class="ml-auto flex items-center gap-2 shrink-0">
                {#if editingCapKey === capKey(tier, chip.id)}
                  <input
                    type="text"
                    bind:value={capDraft}
                    on:keydown={(e) => handleCapKeydown(e, tier, chip.id)}
                    on:blur={cancelCapEdit}
                    placeholder="cap"
                    class="h-6 w-16 rounded border border-input bg-transparent px-1 text-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  />
                {:else}
                  <button
                    type="button"
                    class="rounded border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground hover:text-foreground hover:border-primary transition-colors"
                    on:click={() => startCapEdit(tier, chip)}
                    title="Stop rewarding this stat past a value"
                  >{chip.cap ? `cap ${chip.cap}` : '+ cap'}</button>
                {/if}

                <button
                  type="button"
                  class="text-destructive hover:text-destructive/80 font-bold"
                  on:click={() => removeStat(tier, chip.id)}
                  aria-label="Remove">&times;</button>
              </div>
            </div>

            {#if noteForStat(chip.stat)}
              <p class="mt-1 pl-6 text-[10px] text-muted-foreground italic">{noteForStat(chip.stat)}</p>
            {/if}
          </div>
        {/each}
      </div>

      {#if dndItems[tier]?.length === 0 && !dragging}
        <div class="rounded border border-dashed border-border/70 px-3 py-2 text-[11px] text-muted-foreground">
          No solve stage runs for an empty tier
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
