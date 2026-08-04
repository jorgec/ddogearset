<script lang="ts">
  // The "Add stat ▾" popover body: drill-down tree + search + custom-stat
  // escape hatch (docs/TIERED_SOLVER_FRONTEND_SPEC.md §4.7).
  //
  // This component only OFFERS stats. It never enforces the weapon-damage
  // mutual exclusion — that gate lives in canAddStat() and is applied by the
  // parent, because a stat set can introduce the same conflict without ever
  // going through this picker (§4.4).

  import { createEventDispatcher } from 'svelte';
  import {
      STAT_TAXONOMY,
      FLAT_STATS,
      BUILD_TYPE_PROMOTED_CATEGORY,
      isLeaf,
  } from '$lib/data/statTaxonomy';
  import type { StatTaxonomyCategory, StatTaxonomyLeaf, FlatStatEntry } from '$lib/data/statTaxonomy';

  export let buildType: string = 'Melee';

  const dispatch = createEventDispatcher<{ select: string; close: void }>();

  let search = '';
  let customStat = '';
  let activeCategory: StatTaxonomyCategory | null = null;

  // Build-type relevance is a SOFT highlight: the most relevant branch floats
  // to the top, but nothing is ever hidden (§4.6) — a mixed build must still be
  // able to reach every category.
  $: promoted = BUILD_TYPE_PROMOTED_CATEGORY[buildType];
  $: categories = [...STAT_TAXONOMY].sort((a, b) => {
      const aP = a.label === promoted ? 0 : 1;
      const bP = b.label === promoted ? 0 : 1;
      return aP - bP;
  });

  $: if (activeCategory === null && categories.length > 0) {
      activeCategory = categories[0];
  }

  $: searchTerm = search.trim().toLowerCase();
  // Search matches label AND wire string, so "spelldc" finds "Evocation"
  // even though its visible label never contains that substring (AC-8).
  $: searchResults =
      searchTerm.length > 0
          ? FLAT_STATS.filter(
                (e) =>
                    e.label.toLowerCase().includes(searchTerm) ||
                    e.stat.toLowerCase().includes(searchTerm)
            )
          : [];

  function choose(stat: string) {
      dispatch('select', stat);
      search = '';
      customStat = '';
  }

  function submitCustom() {
      const value = customStat.trim();
      if (value) choose(value);
  }

  function handleCustomKeydown(e: KeyboardEvent) {
      if (e.key === 'Enter') {
          e.preventDefault();
          submitCustom();
      }
  }

  function leavesOf(cat: StatTaxonomyCategory): StatTaxonomyLeaf[] {
      return cat.children.filter(isLeaf) as StatTaxonomyLeaf[];
  }

  function subCategoriesOf(cat: StatTaxonomyCategory): StatTaxonomyCategory[] {
      return cat.children.filter((c) => !isLeaf(c)) as StatTaxonomyCategory[];
  }
</script>

<!-- Width is deliberately modest: this popover opens inside the form's
     left-hand panel, and anything wider spills past the panel's left edge and
     off-screen when anchored to the "Add stat" button. -->
<div class="w-[21rem] max-w-[85vw] rounded-md border border-border bg-popover text-popover-foreground shadow-xl p-3 space-y-3">
  <div class="flex items-center justify-between">
    <span class="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Add a stat</span>
    <button
      type="button"
      class="text-muted-foreground hover:text-foreground text-sm"
      on:click={() => dispatch('close')}
      aria-label="Close">&times;</button>
  </div>

  <input
    type="text"
    bind:value={search}
    placeholder="Search stats…"
    class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
  />

  {#if searchTerm.length > 0}
    <div class="max-h-64 overflow-y-auto space-y-1">
      {#each searchResults as entry (entry.stat)}
        <button
          type="button"
          class="w-full text-left rounded px-2 py-1.5 hover:bg-accent hover:text-accent-foreground transition-colors"
          on:click={() => choose(entry.stat)}
        >
          <span class="text-sm {entry.advanced ? 'text-muted-foreground' : ''}">{entry.label}</span>
          {#if entry.advanced}<span class="ml-1 text-[10px] uppercase text-muted-foreground">Advanced</span>{/if}
          <span class="block text-[10px] text-muted-foreground">{entry.path}</span>
          {#if entry.note}<span class="block text-[10px] text-muted-foreground italic">{entry.note}</span>{/if}
        </button>
      {:else}
        <p class="text-xs text-muted-foreground px-2 py-3">
          No taxonomy match. Use the custom stat field below to add it anyway.
        </p>
      {/each}
    </div>
  {:else}
    <div class="flex gap-2 max-h-64">
      <!-- Left pane: top-level categories -->
      <div class="w-2/5 overflow-y-auto border-r border-border pr-1 space-y-0.5">
        {#each categories as cat (cat.label)}
          <button
            type="button"
            class="w-full text-left rounded px-2 py-1.5 text-xs transition-colors {activeCategory === cat ? 'bg-accent text-accent-foreground font-medium' : 'hover:bg-accent/50'}"
            on:click={() => (activeCategory = cat)}
          >
            {cat.label}
            {#if cat.label === promoted}<span class="ml-1 text-[9px] uppercase text-primary">Relevant</span>{/if}
          </button>
        {/each}
      </div>

      <!-- Right pane: leaves + one level of sub-categories -->
      <div class="w-3/5 overflow-y-auto pl-1 space-y-1">
        {#if activeCategory}
          {#each leavesOf(activeCategory) as leaf (leaf.stat)}
            <button
              type="button"
              class="w-full text-left rounded px-2 py-1.5 hover:bg-accent hover:text-accent-foreground transition-colors"
              on:click={() => choose(leaf.stat)}
            >
              <span class="text-sm {leaf.advanced ? 'text-muted-foreground' : ''}">{leaf.label}</span>
              {#if leaf.advanced}<span class="ml-1 text-[10px] uppercase text-muted-foreground">Advanced</span>{/if}
              {#if leaf.note}<span class="block text-[10px] text-muted-foreground italic">{leaf.note}</span>{/if}
            </button>
          {/each}

          {#each subCategoriesOf(activeCategory) as sub (sub.label)}
            <div class="pt-1">
              <p class="px-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{sub.label}</p>
              {#each leavesOf(sub) as leaf (leaf.stat)}
                <button
                  type="button"
                  class="w-full text-left rounded px-2 py-1.5 hover:bg-accent hover:text-accent-foreground transition-colors"
                  on:click={() => choose(leaf.stat)}
                >
                  <span class="text-sm {leaf.advanced ? 'text-muted-foreground' : ''}">{leaf.label}</span>
                  {#if leaf.advanced}<span class="ml-1 text-[10px] uppercase text-muted-foreground">Advanced</span>{/if}
                  {#if leaf.note}<span class="block text-[10px] text-muted-foreground italic">{leaf.note}</span>{/if}
                </button>
              {/each}
            </div>
          {/each}
        {/if}
      </div>
    </div>
  {/if}

  <!-- Pinned at all times: the taxonomy must never be able to wall off a stat
       the user knows about but the tree doesn't list yet (§4.7). -->
  <div class="border-t border-border pt-2 space-y-1">
    <label class="text-[10px] uppercase tracking-wider text-muted-foreground" for="custom-stat">
      Use a custom stat name…
    </label>
    <div class="flex gap-2">
      <input
        id="custom-stat"
        type="text"
        bind:value={customStat}
        on:keydown={handleCustomKeydown}
        placeholder="e.g. constitution"
        class="flex h-8 w-full rounded-md border border-input bg-transparent px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      />
      <button
        type="button"
        class="rounded-md bg-secondary text-secondary-foreground border border-border px-3 text-xs hover:bg-secondary/80 transition-colors"
        on:click={submitCustom}
      >Add</button>
    </div>
  </div>
</div>
