<script lang="ts">
  // Owned Items — standalone screen for browsing a Trove inventory export.
  // Distinct from JobConfigurationForm's "Owned Items (Trove Import)" section:
  // that one feeds $configStore.owned_item_names to constrain the solver
  // (docs/TROVE_INVENTORY_IMPORT_SPEC.md); this one is read-only browsing,
  // items-only (no augments — kept simple per explicit scope), pre-filtered
  // to only names that actually matched a real DDOBuilderV2 item (Go's
  // LoadTroveFromPath cross-references itemsByName itself, so nothing
  // "non-usable" ever reaches this list).
  import { troveImportStore, troveImporting } from '$lib/store';
  import ItemDetail from './ItemDetail.svelte';
  import { fly, fade } from 'svelte/transition';

  // Backed by a module-level store (store.ts), not local state. The dashboard
  // redesign now keeps this panel mounted when another readout is fronted, so
  // the original reason (App.svelte destroying it on every tab switch) no
  // longer applies — but the store is still the right home, because it is the
  // SAME store the solver form's "Owned Items (Trove Import)" accordion reads
  // and writes: a CSV dropped on either zone has to show up in both.
  let searchQuery = '';

  let selectedItemName: string | null = null;

  $: filteredItems = searchQuery.trim()
    ? $troveImportStore.items.filter(i => i.name.toLowerCase().includes(searchQuery.trim().toLowerCase()))
    : $troveImportStore.items;

  function openDrawer(name: string) {
    selectedItemName = name;
  }

  function closeDrawer() {
    selectedItemName = null;
  }
</script>

<div class="panel flex flex-col h-full space-y-3 p-3">
  <div class="space-y-2 shrink-0">
    <div>
      <h2 class="panel-title text-sm">Owned Items</h2>
      <p class="text-[11px] text-steel mt-1">
        Browse a Trove inventory export. Only items that match a real DDOBuilderV2
        item are shown — no augments, no filigrees, no unmatched/unusable rows.
      </p>
    </div>
    <!-- Import is drag-and-drop only. The inline custom property is what Wails
         hit-tests against on drop (App.svelte registers the handler); it must
         be inline rather than a class, because Wails reads element.style when
         it walks up to flag the active target. -->
    <div
      style="--wails-drop-target: drop"
      class="drop-zone w-full rounded border border-dashed border-carved px-3 py-4 text-center transition-colors"
    >
      {#if $troveImporting}
        <p class="text-xs text-gold">Importing…</p>
      {:else}
        <p class="text-xs text-vellum">Drag a Trove CSV export here</p>
        <p class="text-[10px] text-steel mt-1">
          {$troveImportStore.items.length > 0 ? 'Drop another to replace it' : 'Your inventory export from Trove (.csv)'}
        </p>
      {/if}
    </div>
  </div>

  {#if $troveImportStore.items.length > 0}
    <div class="space-y-2 shrink-0">
      <p class="text-[11px] text-steel italic">
        {$troveImportStore.fileName} — {$troveImportStore.totalRows} rows, {$troveImportStore.items.length} usable items
      </p>
      <input
        type="text"
        bind:value={searchQuery}
        placeholder="Filter by name..."
        class="trove-filter w-full flex h-9 rounded-md border border-input bg-void px-3 py-1 text-sm placeholder:text-steel/50 focus:outline-none"
      />
    </div>

    <!-- §4.4 — "a condensed table view". A real <table> needs five columns
         that cannot fit the 30%-wide readout column, so each row folds into
         a two-line entry: name + ML on top, provenance beneath. -->
    <div class="flex-1 min-h-0 overflow-y-auto -mx-1 px-1">
      <ul class="divide-y divide-carved">
        {#each filteredItems as item (item.name)}
          <li>
            <button
              type="button"
              on:click={() => openDrawer(item.name)}
              class="w-full text-left py-1.5 px-1.5 rounded hover:bg-carved/50 transition-colors group"
            >
              <div class="flex items-baseline gap-2">
                <span class="flex-1 text-xs font-medium text-vellum truncate group-hover:text-gold transition-colors" title={item.name}>
                  {item.name}
                </span>
                <span class="text-[10px] text-steel shrink-0">ML {item.minLevel}</span>
              </div>
              <div class="text-[10px] text-steel/70 truncate">
                {[item.character, item.location, item.packId].filter(Boolean).join(' · ') || '—'}
              </div>
            </button>
          </li>
        {/each}
      </ul>
      {#if filteredItems.length === 0}
        <p class="text-steel text-xs py-6 text-center">No items match "{searchQuery}".</p>
      {/if}
    </div>
  {:else if !$troveImporting}
    <div class="flex-1 flex flex-col items-center justify-center text-center text-muted-foreground p-12">
      <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round" class="mb-4 opacity-50"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M7 7h.01"/><path d="M17 7h.01"/><path d="M7 17h.01"/><path d="M17 17h.01"/></svg>
      <p>Drag a Trove inventory CSV export onto the panel above to see your usable items here.</p>
    </div>
  {/if}
</div>

<!-- Sliding drawer, matching GearsetEditor's use of ItemDetail — read-only
     (mode="view", no slot/slotDetail) since this is a browsing screen, not a
     gearset edit. Uses Svelte's `transition:fly` (not a manually-toggled
     class) — the drawer's <div> only exists in the DOM while
     selectedItemName is set, so a CSS class-based transform transition would
     have no "closed" state to animate from; `fly` handles the enter/exit
     animation itself regardless. -->
{#if selectedItemName}
  <button
    class="fixed inset-0 z-40 bg-void/70 backdrop-blur-md"
    on:click={closeDrawer}
    aria-label="Close item details"
    transition:fade={{ duration: 150 }}
  ></button>
  <div
    class="fixed top-0 right-0 z-50 h-full w-full max-w-xl bg-background border-l border-border shadow-2xl overflow-y-auto"
    transition:fly={{ x: 400, duration: 200 }}
  >
    <div class="sticky top-0 z-10 flex items-center justify-between px-6 py-4 bg-background/95 backdrop-blur border-b border-border">
      <h3 class="font-semibold text-lg truncate pr-4">{selectedItemName}</h3>
      <button
        type="button"
        on:click={closeDrawer}
        class="text-muted-foreground hover:text-foreground p-1 shrink-0"
        aria-label="Close"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
      </button>
    </div>
    <div class="p-6">
      <ItemDetail itemName={selectedItemName} mode="view" />
    </div>
  </div>
{/if}
