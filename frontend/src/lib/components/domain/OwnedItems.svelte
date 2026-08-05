<script lang="ts">
  // Owned Items — standalone screen for browsing a Trove inventory export.
  // Distinct from JobConfigurationForm's "Owned Items (Trove Import)" section:
  // that one feeds $configStore.owned_item_names to constrain the solver
  // (docs/TROVE_INVENTORY_IMPORT_SPEC.md); this one is read-only browsing,
  // items-only (no augments — kept simple per explicit scope), pre-filtered
  // to only names that actually matched a real DDOBuilderV2 item (Go's
  // GetTroveOwnedItems cross-references itemsByName itself, so nothing
  // "non-usable" ever reaches this list).
  import { showToast, troveImportStore } from '$lib/store';
  import { loadTroveCsv } from '$lib/services/troveImport';
  import ItemDetail from './ItemDetail.svelte';
  import { fly, fade } from 'svelte/transition';

  // Backed by a module-level store (store.ts), not local state — this screen
  // is destroyed/recreated by App.svelte's {#if $currentTab === 'ownedItems'}
  // block on every tab switch, so a plain `let` here would lose the loaded
  // CSV the moment the user looked at another tab. It's the same store the
  // solver-form accordion reads/writes, so a CSV loaded from either screen
  // shows up in both.
  let loading = false;
  let searchQuery = '';

  let selectedItemName: string | null = null;

  $: filteredItems = searchQuery.trim()
    ? $troveImportStore.items.filter(i => i.name.toLowerCase().includes(searchQuery.trim().toLowerCase()))
    : $troveImportStore.items;

  function loadTroveCSV() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.csv';
    input.onchange = (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      loading = true;
      const reader = new FileReader();
      reader.onload = async (re) => {
        try {
          const csvContent = re.target?.result as string;
          const result = await loadTroveCsv(csvContent, file.name);
          if (!result.success) {
            showToast('Failed to load Trove inventory: ' + (result.errorMessage || 'unknown error'), 'error');
            return;
          }
          showToast(`Loaded ${result.totalRows} rows — ${result.itemsCount} usable items.`, 'success');
        } catch (e) {
          showToast('Failed to load Trove inventory: ' + e, 'error');
        } finally {
          loading = false;
        }
      };
      reader.onerror = () => {
        loading = false;
        showToast('Failed to read the selected file.', 'error');
      };
      reader.readAsText(file);
    };
    input.click();
  }

  function openDrawer(name: string) {
    selectedItemName = name;
  }

  function closeDrawer() {
    selectedItemName = null;
  }
</script>

<div class="flex flex-col space-y-6 p-4 md:p-6 bg-background rounded-lg border border-border shadow-sm">
  <div class="flex items-center justify-between border-b border-border/50 pb-4">
    <div>
      <h2 class="text-2xl font-bold tracking-tight">Owned Items</h2>
      <p class="text-sm text-muted-foreground mt-1">
        Browse a Trove inventory export. Only items that match a real DDOBuilderV2
        item are shown — no augments, no filigrees, no unmatched/unusable rows.
      </p>
    </div>
    <button
      type="button"
      on:click={loadTroveCSV}
      disabled={loading}
      class="px-4 py-2 bg-secondary text-secondary-foreground border border-border rounded shadow-sm hover:bg-secondary/80 transition-colors disabled:opacity-50"
    >
      {loading ? 'Loading...' : $troveImportStore.items.length > 0 ? 'Load a different CSV' : 'Load Trove CSV...'}
    </button>
  </div>

  {#if $troveImportStore.items.length > 0}
    <div class="flex items-center justify-between">
      <p class="text-sm text-muted-foreground italic">
        {$troveImportStore.fileName} — {$troveImportStore.totalRows} rows, {$troveImportStore.items.length} usable items
      </p>
      <input
        type="text"
        bind:value={searchQuery}
        placeholder="Filter by name..."
        class="w-64 flex h-9 rounded-md border border-input bg-background px-3 py-1 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      />
    </div>

    <div class="overflow-x-auto">
      <table class="w-full text-sm text-left">
        <thead class="text-xs text-muted-foreground uppercase bg-muted/50 border-b border-border">
          <tr>
            <th class="px-3 py-2 font-medium">Name</th>
            <th class="px-3 py-2 font-medium">ML</th>
            <th class="px-3 py-2 font-medium">Pack</th>
            <th class="px-3 py-2 font-medium">Character</th>
            <th class="px-3 py-2 font-medium">Location</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-border">
          {#each filteredItems as item (item.name)}
            <tr class="hover:bg-muted/30 transition-colors">
              <td class="px-3 py-2">
                <button
                  type="button"
                  on:click={() => openDrawer(item.name)}
                  class="font-medium text-primary hover:underline text-left"
                >
                  {item.name}
                </button>
              </td>
              <td class="px-3 py-2 text-muted-foreground">{item.minLevel}</td>
              <td class="px-3 py-2 text-xs italic text-muted-foreground">{item.packId || '—'}</td>
              <td class="px-3 py-2 text-xs text-muted-foreground">{item.character || '—'}</td>
              <td class="px-3 py-2 text-xs text-muted-foreground">{item.location || '—'}</td>
            </tr>
          {/each}
        </tbody>
      </table>
      {#if filteredItems.length === 0}
        <p class="text-muted-foreground text-sm py-6 text-center">No items match "{searchQuery}".</p>
      {/if}
    </div>
  {:else if !loading}
    <div class="flex-1 flex flex-col items-center justify-center text-center text-muted-foreground p-12">
      <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round" class="mb-4 opacity-50"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M7 7h.01"/><path d="M17 7h.01"/><path d="M7 17h.01"/><path d="M17 17h.01"/></svg>
      <p>Load a Trove inventory CSV export to see your usable items here.</p>
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
    class="fixed inset-0 z-40 bg-black/40"
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
