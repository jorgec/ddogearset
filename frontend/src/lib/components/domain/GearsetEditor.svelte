<script lang="ts">
  import { resultStore, configStore, isOptimizing, hydrateConfigFromSlots, showToast } from '$lib/store';
  import { GetAvailableItems, GetItemDetails, RunOptimization, GetAvailableFiligrees } from '../../../../wailsjs/go/main/App';
  import type { models, main } from '../../../../wailsjs/go/models';
  import ItemDetail from './ItemDetail.svelte';

  const baseSlots = ['Helmet', 'Necklace', 'Trinket', 'Cloak', 'Belt', 'Ring_1', 'Ring_2', 'Gloves', 'Boots', 'Bracers', 'Armor', 'Goggles', 'Weapon1', 'Weapon2'];

  let selectedSlot: string | null = null;
  let availableItems: models.XMLItem[] = [];
  let isFetchingItems = false;
  let searchQuery = "";
  let searchTimeout: any;
  
  let editingFiligreeIdx: number | null = null;
  let editingFiligreeType: "weapon" | "artifact" | null = null;
  let availableFiligrees: models.XMLFiligree[] = [];
  let isFetchingFiligrees = false;
  let filigreeSearchQuery = "";
  let filigreeSearchTimeout: any;
  let filigreeSetFilter = "";
  
  $: uniqueFiligreeSets = Array.from(new Set(availableFiligrees.map(f => f.SetName))).filter(Boolean).sort();
  $: filteredFiligrees = availableFiligrees.filter(f => !filigreeSetFilter || f.SetName === filigreeSetFilter);
  
  let selectedItemDetails: models.XMLItem | null = null;
  
  function isWeapon(item: models.XMLItem) {
      if (!item.EquipmentSlot || !item.EquipmentSlot.Slots) return false;
      return item.EquipmentSlot.Slots.includes("Weapon1") || item.EquipmentSlot.Slots.includes("Weapon2") || item.EquipmentSlot.Slots.includes("Weapon");
  }

  function getArtifactFiligreeCount(item: models.XMLItem) {
      if (item.MinorArtifact === undefined) return 0;
      if (item.Name === "Epic Voice of the Master") return 1;
      if (item.MinLevel >= 33) return 5;
      if (item.MinLevel >= 31) return 4;
      if (item.MinLevel >= 30) return 3;
      return 1;
  }
  
  function getWeaponFiligreeCount(item: models.XMLItem) {
      if (!isWeapon(item)) return 0;
      if (item.MinLevel < 20) return 0;
      return 10; // Sentient weapons can hold up to 10 with max sparks. We'll show 10 slots.
  }
  
  $: if (!$resultStore) {
      $resultStore = { success: true, timeTaken: 0, gearSet: {}, realizedStats: {}, activeSets: [], filigrees: [] };
  }
  $: if ($resultStore && !$resultStore.gearSet) {
      $resultStore.gearSet = {};
  }

  // Auto-hydrate pre_equipped/pre_filled_augments/pre_filled_filigrees whenever a new
  // solved/loaded gearset's per-slot detail becomes available (Auto Solver run or
  // .ddogearset file load), so items placed here show their augments/filigrees
  // immediately instead of only after clicking "Calculate Stats". Only fills gaps —
  // never overwrites anything already manually edited (see hydrateConfigFromSlots).
  let hydratedSlotsRef: Record<string, any> | undefined = undefined;
  $: if ($resultStore?.slots && $resultStore.slots !== hydratedSlotsRef) {
      hydratedSlotsRef = $resultStore.slots;
      const hydrated = hydrateConfigFromSlots($configStore, $resultStore.slots);
      if (hydrated) {
          $configStore.pre_equipped = hydrated.pre_equipped;
          $configStore.pre_filled_augments = hydrated.pre_filled_augments;
          $configStore.pre_filled_filigrees = hydrated.pre_filled_filigrees;
      }
  }

  async function handleSlotClick(slot: string) {
      selectedSlot = slot;
      searchQuery = ""; // reset search on new slot click
      await fetchItems(slot, "");
  }
  
  async function fetchItems(slot: string, query: string) {
      isFetchingItems = true;
      const maxLvl = $configStore.max_level || 34;
      
      try {
          const res = await GetAvailableItems(slot, maxLvl, query);
          // Minor artifact enforcement
          const currentArtifacts = Object.values($resultStore.gearSet).filter(iName => {
              // we don't have isMinor readily available without fetching details, but assuming we can check if it's already an artifact.
              // For simplicity, we just show all items and enforce on select.
              return false; // To fully enforce, we'd need item details of all equipped.
          });
          availableItems = res || [];
      } catch(e) {
          console.error(e);
      } finally {
          isFetchingItems = false;
      }
  }

  function handleSearchInput() {
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(() => {
          if (selectedSlot) {
              fetchItems(selectedSlot, searchQuery);
          }
      }, 300);
  }

  async function handleItemClick(slot: string, itemName: string) {
      selectedSlot = slot;
      availableItems = [];
      editingFiligreeIdx = null;
      editingFiligreeType = null;
      try {
          selectedItemDetails = await GetItemDetails(itemName);
      } catch(e) {
          console.error(e);
      }
  }

  async function assignMinorArtifact(item: models.XMLItem) {
      if (!selectedSlot) return;
      const baseSlot = selectedSlot.replace('_1', '').replace('_2', '');
      $configStore.reserved_minor_artifact_slot = baseSlot;
      $configStore.is_dino_artifact = item.Name.toLowerCase().includes('dinosaur');
      
      for (const [slot, name] of Object.entries($resultStore.gearSet)) {
          if (slot !== selectedSlot && name) {
              try {
                  const details = await GetItemDetails(name as string);
                  if (details && details.MinorArtifact !== undefined && details.MinorArtifact !== null) {
                      clearSlot(slot);
                  }
              } catch (e) {
                  console.error(e);
              }
          }
      }
  }

  async function handleMinorArtifactToggle(checked: boolean) {
      if (!selectedItemDetails || !selectedSlot) return;
      if (checked) {
          selectedItemDetails.MinorArtifact = "";
          await assignMinorArtifact(selectedItemDetails);
      } else {
          selectedItemDetails.MinorArtifact = undefined as any;
          const baseSlot = selectedSlot.replace('_1', '').replace('_2', '');
          if ($configStore.reserved_minor_artifact_slot === baseSlot) {
              $configStore.reserved_minor_artifact_slot = "Any";
          }
      }
  }

  async function selectItem(item: models.XMLItem) {
      if (!selectedSlot) return;
      
      const isMinor = item.MinorArtifact !== undefined && item.MinorArtifact !== null;
      if (isMinor) {
          await assignMinorArtifact(item);
      }

      $resultStore.gearSet[selectedSlot] = item.Name;
      $configStore.pre_equipped[selectedSlot] = item.Name;
      // Also clear existing augments for this slot if item changes
      if ($configStore.pre_filled_augments[selectedSlot]) {
          delete $configStore.pre_filled_augments[selectedSlot];
      }
      $resultStore.gearSet = {...$resultStore.gearSet};
      $configStore.pre_equipped = {...$configStore.pre_equipped};
      $configStore.pre_filled_augments = {...$configStore.pre_filled_augments};
      selectedItemDetails = item;
      availableItems = []; // Close dropdown
  }

  function clearSlot(slot: string) {
      delete $resultStore.gearSet[slot];
      delete $configStore.pre_equipped[slot];
      if ($configStore.pre_filled_augments[slot]) {
          delete $configStore.pre_filled_augments[slot];
      }
      $resultStore.gearSet = {...$resultStore.gearSet};
      $configStore.pre_equipped = {...$configStore.pre_equipped};
      $configStore.pre_filled_augments = {...$configStore.pre_filled_augments};
      if (selectedSlot === slot) {
          selectedItemDetails = null;
      }
  }
  
  async function openFiligreePicker(idx: number, type: "weapon" | "artifact") {
      editingFiligreeIdx = idx;
      editingFiligreeType = type;
      filigreeSearchQuery = "";
      filigreeSetFilter = "";
      await fetchFiligrees("");
  }
  
  async function fetchFiligrees(query: string) {
      isFetchingFiligrees = true;
      try {
          availableFiligrees = await GetAvailableFiligrees(query) || [];
      } catch (e) {
          console.error(e);
      } finally {
          isFetchingFiligrees = false;
      }
  }
  
  function handleFiligreeSearchInput() {
      clearTimeout(filigreeSearchTimeout);
      filigreeSearchTimeout = setTimeout(() => {
          fetchFiligrees(filigreeSearchQuery);
      }, 300);
  }
  
  function selectFiligree(idx: number, fil: models.XMLFiligree) {
      if (!editingFiligreeType) return;
      if (!$configStore.pre_filled_filigrees[editingFiligreeType]) {
          $configStore.pre_filled_filigrees[editingFiligreeType] = [];
      }
      while ($configStore.pre_filled_filigrees[editingFiligreeType].length <= idx) {
          $configStore.pre_filled_filigrees[editingFiligreeType].push("");
      }
      $configStore.pre_filled_filigrees[editingFiligreeType][idx] = fil.Name;
      $configStore.pre_filled_filigrees = {...$configStore.pre_filled_filigrees};
      editingFiligreeIdx = null;
      editingFiligreeType = null;
  }
  
  function clearFiligree(idx: number, type: "weapon" | "artifact") {
      if (!$configStore.pre_filled_filigrees[type]) return;
      $configStore.pre_filled_filigrees[type][idx] = "";
      $configStore.pre_filled_filigrees = {...$configStore.pre_filled_filigrees};
  }

  function clearAll() {
      $resultStore = { success: true, timeTaken: 0, gearSet: {}, realizedStats: {}, activeSets: [], filigrees: [] };
      $configStore.pre_equipped = {};
      $configStore.pre_filled_augments = {};
      $configStore.pre_filled_filigrees = { weapon: [], artifact: [] };
      selectedItemDetails = null;
      selectedSlot = null;
      availableItems = [];
  }

  async function calculateGearSet() {
      $isOptimizing = true;
      try {
          // Non-destructive/read-only recompute: fill in pre_equipped/
          // pre_filled_augments/pre_filled_filigrees from the last known
          // solved/loaded gearset for anything not already manually edited
          // this session. See docs/ENGINEERING.md "Known Issues".
          const hydrated = hydrateConfigFromSlots($configStore, $resultStore?.slots);
          if (hydrated) {
              $configStore.pre_equipped = hydrated.pre_equipped;
              $configStore.pre_filled_augments = hydrated.pre_filled_augments;
              $configStore.pre_filled_filigrees = hydrated.pre_filled_filigrees;
          }
          // Calculate mode travels on the request, not on the shared store.
          // The old mutate-then-restore made "calculate_only" briefly visible
          // to every other subscriber for the duration of the call, and was
          // unsafe if the user triggered a second action mid-flight.
          // Cast mirrors store.ts: the spread drops the wails class's
          // convertValues method, which nothing on this path calls.
          const res = await RunOptimization(
              { ...$configStore, mode: 'calculate' } as unknown as main.OptimizationPayload
          );
          if (res && res.success) {
              $resultStore = res;
              showToast('Stats recalculated.', 'success');
          } else {
              showToast(res?.errorMessage || 'Calculation failed.', 'error');
          }
      } catch (e) {
          console.error(e);
          showToast('Calculation failed: ' + e, 'error');
      } finally {
          $isOptimizing = false;
      }
  }
</script>

<div class="h-full flex space-x-6 overflow-hidden">
  <!-- Left Side: Gearset Slots -->
  <div class="w-1/2 flex flex-col space-y-4 overflow-y-auto pr-2 pb-8">
      <div class="flex justify-between items-center">
          <h2 class="text-xl font-semibold tracking-tight">Equipment Slots</h2>
          <div class="flex space-x-2">
              <button on:click={clearAll} class="px-3 py-1 text-sm bg-destructive text-destructive-foreground hover:bg-destructive/90 rounded transition-colors">Clear</button>
              <button on:click={calculateGearSet} disabled={$isOptimizing} class="px-3 py-1 text-sm bg-primary text-primary-foreground hover:bg-primary/90 rounded transition-colors flex items-center">
                  {#if $isOptimizing}
                      <span class="mr-1 h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
                  {/if}
                  Calculate Stats
              </button>
          </div>
      </div>
      <div class="grid grid-cols-1 gap-2">
          {#each baseSlots as slot}
              <div class="glass-panel p-3 flex justify-between items-center transition-colors {selectedSlot === slot ? 'ring-2 ring-primary' : ''}">
                  <div class="font-medium w-24 border-r border-border/50">{slot.replace('_1', ' 1').replace('_2', ' 2')}</div>
                  
                  {#if $resultStore.gearSet[slot]}
                      <button class="flex-1 text-left px-4 font-mono text-primary truncate hover:underline" on:click={() => handleItemClick(slot, $resultStore.gearSet[slot])}>
                          {$resultStore.gearSet[slot]}
                      </button>
                      <button on:click={() => clearSlot(slot)} class="text-muted-foreground hover:text-destructive p-1">
                          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-x"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
                      </button>
                  {:else}
                      <button class="flex-1 text-left px-4 text-muted-foreground italic hover:text-primary" on:click={() => handleSlotClick(slot)}>
                          Empty Slot (Click to add)
                      </button>
                  {/if}
              </div>
          {/each}
      </div>
  </div>

  <!-- Right Side: Details & Dropdowns -->
  <div class="w-1/2 glass-panel p-6 flex flex-col overflow-y-auto">
      {#if availableItems.length > 0 || searchQuery !== ""}
          <div class="flex justify-between items-center mb-4">
              <h3 class="font-semibold text-lg">Select {selectedSlot}</h3>
              <button class="text-muted-foreground hover:text-primary" on:click={() => {availableItems = []; searchQuery = "";}}>Cancel</button>
          </div>
          <div class="mb-4">
              <input type="text" bind:value={searchQuery} on:input={handleSearchInput} placeholder="Search names or raw XML data..." class="w-full flex h-10 rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50" />
          </div>
          <div class="flex-1 overflow-y-auto space-y-2">
              {#if isFetchingItems}
                  <p class="text-muted-foreground animate-pulse">Loading items...</p>
              {:else}
                  {#each availableItems as item}
                      <button on:click={() => selectItem(item)} class="w-full text-left p-3 rounded bg-muted/30 hover:bg-muted border border-transparent hover:border-border transition-colors">
                          <div class="font-medium">{item.Name}</div>
                          <div class="text-xs text-muted-foreground">ML: {item.MinLevel}</div>
                      </button>
                  {/each}
                  {#if availableItems.length === 0}
                      <p class="text-muted-foreground text-sm">No items found for this slot and level range.</p>
                  {/if}
              {/if}
          </div>
      {:else if selectedItemDetails}
          <!-- The whole detail view now lives in ItemDetail.svelte, which
               self-fetches the full item (buffs, weapon/armor profile, augment
               choices, set bonuses, effects, acquisition) and owns the augment
               picker. slotDetail comes from the same slot being displayed so the
               credited-marker badges refer to the right solve output (EC-12). -->
          <ItemDetail
              itemName={selectedItemDetails.Name}
              slot={selectedSlot}
              slotDetail={selectedSlot ? ($resultStore?.slots?.[selectedSlot] ?? null) : null}
              mode="edit"
              on:minorArtifactToggle={(e) => handleMinorArtifactToggle(e.detail.checked)}
          />
      {:else}
          <div class="flex-1 flex flex-col items-center justify-center text-center text-muted-foreground p-12">
              <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round" class="mb-4 opacity-50"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M7 7h.01"/><path d="M17 7h.01"/><path d="M7 17h.01"/><path d="M17 17h.01"/></svg>
              <p>Select a slot on the left to view or edit its item.</p>
          </div>
      {/if}
  </div>
</div>
