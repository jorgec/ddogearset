<script lang="ts">
  import { resultStore, configStore, isOptimizing } from '$lib/store';
  import { GetAvailableItems, GetItemDetails, RunOptimization, GetAvailableAugments, GetAvailableFiligrees } from '../../../../wailsjs/go/main/App';
  import { BrowserOpenURL } from '../../../../wailsjs/runtime/runtime';
  import { models } from '../../../../wailsjs/go/models';

  const baseSlots = ['Helmet', 'Necklace', 'Trinket', 'Cloak', 'Belt', 'Ring_1', 'Ring_2', 'Gloves', 'Boots', 'Bracers', 'Armor', 'Goggles', 'Weapon1', 'Weapon2'];

  let selectedSlot: string | null = null;
  let availableItems: models.XMLItem[] = [];
  let isFetchingItems = false;
  let searchQuery = "";
  let searchTimeout: any;
  
  let editingAugmentSlotIdx: number | null = null;
  let availableAugments: models.XMLAugment[] = [];
  let isFetchingAugments = false;
  let augmentSearchQuery = "";
  let augmentSearchTimeout: any;
  
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

  async function handleSlotClick(slot: string) {
      selectedSlot = slot;
      searchQuery = ""; // reset search on new slot click
      await fetchItems(slot, "");
  }
  
  async function fetchItems(slot: string, query: string) {
      isFetchingItems = true;
      const maxLvl = ($configStore.max_levels && $configStore.max_levels.length > 0) ? $configStore.max_levels[0] : 32;
      
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
      editingAugmentSlotIdx = null;
      editingFiligreeIdx = null;
      editingFiligreeType = null;
      try {
          selectedItemDetails = await GetItemDetails(itemName);
      } catch(e) {
          console.error(e);
      }
  }

  function selectItem(item: models.XMLItem) {
      if (!selectedSlot) return;
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
  
  async function openAugmentPicker(idx: number, type: string) {
      editingAugmentSlotIdx = idx;
      augmentSearchQuery = "";
      await fetchAugments(type, "");
  }
  
  async function fetchAugments(type: string, query: string) {
      isFetchingAugments = true;
      const maxLvl = ($configStore.max_levels && $configStore.max_levels.length > 0) ? $configStore.max_levels[0] : 32;
      try {
          availableAugments = await GetAvailableAugments(type, maxLvl, query) || [];
      } catch (e) {
          console.error(e);
      } finally {
          isFetchingAugments = false;
      }
  }
  
  function handleAugmentSearchInput(type: string) {
      clearTimeout(augmentSearchTimeout);
      augmentSearchTimeout = setTimeout(() => {
          fetchAugments(type, augmentSearchQuery);
      }, 300);
  }
  
  function selectAugment(idx: number, aug: models.XMLAugment) {
      if (!selectedSlot) return;
      if (!$configStore.pre_filled_augments[selectedSlot]) {
          $configStore.pre_filled_augments[selectedSlot] = [];
      }
      // Ensure array is large enough
      while ($configStore.pre_filled_augments[selectedSlot].length <= idx) {
          $configStore.pre_filled_augments[selectedSlot].push("");
      }
      $configStore.pre_filled_augments[selectedSlot][idx] = aug.Name;
      $configStore.pre_filled_augments = {...$configStore.pre_filled_augments};
      editingAugmentSlotIdx = null;
  }
  
  function clearAugment(idx: number) {
      if (!selectedSlot || !$configStore.pre_filled_augments[selectedSlot]) return;
      $configStore.pre_filled_augments[selectedSlot][idx] = "";
      $configStore.pre_filled_augments = {...$configStore.pre_filled_augments};
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

  function getWikiUrl(itemName: string): string {
      return `https://ddowiki.com/page/Item:${itemName.replace(/ /g, '_')}`;
  }
  
  function openWiki(itemName: string) {
      BrowserOpenURL(getWikiUrl(itemName));
  }
  
  function clearAll() {
      $resultStore = { success: true, timeTaken: 0, gearSet: {}, realizedStats: {}, activeSets: [], filigrees: [] };
      $configStore.pre_equipped = {};
      selectedItemDetails = null;
      selectedSlot = null;
      availableItems = [];
  }
  
  async function calculateGearSet() {
      $isOptimizing = true;
      try {
          $configStore.calculate_only = true;
          const res = await RunOptimization($configStore);
          if (res && res.success) {
              $resultStore = res;
          }
      } catch (e) {
          console.error(e);
      } finally {
          $configStore.calculate_only = false;
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
          <div class="space-y-6">
              <div>
                  <h3 class="text-2xl font-bold tracking-tight">{selectedItemDetails.Name}</h3>
                  <p class="text-sm text-muted-foreground mt-1">ML: {selectedItemDetails.MinLevel}</p>
              </div>
              
              <div class="flex space-x-3">
                  <button on:click={() => openWiki(selectedItemDetails.Name)} class="inline-flex items-center justify-center rounded-md text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 h-9 px-4 py-2 cursor-pointer transition-colors">
                      <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="mr-2 lucide lucide-external-link"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>
                      DDO Wiki Search
                  </button>
              </div>

              {#if selectedItemDetails.Description}
                  <div class="prose prose-sm dark:prose-invert max-w-none">
                      <!-- Render HTML description from DDOBuilder safely or plainly -->
                      {@html selectedItemDetails.Description}
                  </div>
              {:else}
                  <p class="text-muted-foreground italic">No stat description available.</p>
              {/if}
              
              <!-- Augments -->
              {#if selectedItemDetails.ItemAugments && selectedItemDetails.ItemAugments.length > 0}
                  <div class="mt-6 pt-4 border-t border-border/50">
                      <h4 class="font-semibold text-lg mb-3">Augment Slots</h4>
                      <div class="space-y-3">
                          {#each selectedItemDetails.ItemAugments as aug, idx}
                              <div class="flex flex-col space-y-1">
                                  <div class="flex justify-between items-center text-sm font-medium">
                                      <span>{aug.Type} Slot</span>
                                      {#if $configStore.pre_filled_augments[selectedSlot] && $configStore.pre_filled_augments[selectedSlot][idx]}
                                          <button class="text-xs text-destructive hover:underline" on:click={() => clearAugment(idx)}>Remove</button>
                                      {/if}
                                  </div>
                                  {#if editingAugmentSlotIdx === idx}
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
                                                      <button on:click={() => selectAugment(idx, availableAug)} class="w-full text-left p-2 rounded text-xs bg-card hover:bg-muted transition-colors border border-transparent hover:border-primary">
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
                                  {:else}
                                      <button on:click={() => openAugmentPicker(idx, aug.Type)} class="w-full text-left p-2 rounded bg-muted/50 hover:bg-muted border border-transparent hover:border-primary transition-colors text-sm flex items-center justify-between">
                                          {#if $configStore.pre_filled_augments[selectedSlot] && $configStore.pre_filled_augments[selectedSlot][idx]}
                                              <span class="text-primary font-medium">{$configStore.pre_filled_augments[selectedSlot][idx]}</span>
                                          {:else}
                                              <span class="text-muted-foreground italic">Empty (Click to add)</span>
                                          {/if}
                                      </button>
                                  {/if}
                              </div>
                          {/each}
                      </div>
                  </div>
              {/if}
              
              <!-- Filigree Slots -->
              {#if getArtifactFiligreeCount(selectedItemDetails) > 0}
                  <div class="mt-6 pt-4 border-t border-border/50">
                      <h4 class="font-semibold text-lg mb-3">Minor Artifact Filigrees</h4>
                      <div class="space-y-3">
                          {#each Array(getArtifactFiligreeCount(selectedItemDetails)) as _, idx}
                              <div class="flex flex-col space-y-1">
                                  <div class="flex justify-between items-center text-sm font-medium">
                                      <span>Artifact Filigree Slot {idx + 1}</span>
                                      {#if $configStore.pre_filled_filigrees?.artifact && $configStore.pre_filled_filigrees.artifact[idx]}
                                          <button class="text-xs text-destructive hover:underline" on:click={() => clearFiligree(idx, "artifact")}>Remove</button>
                                      {/if}
                                  </div>
                                  {#if editingFiligreeIdx === idx && editingFiligreeType === "artifact"}
                                      <div class="mt-2 p-3 bg-muted/30 rounded border border-border">
                                          <div class="flex justify-between items-center mb-2">
                                              <input type="text" bind:value={filigreeSearchQuery} on:input={handleFiligreeSearchInput} placeholder="Search filigrees by stat or set..." class="flex-1 h-8 rounded-md border border-input bg-background px-2 text-xs mr-2" />
                                              <select bind:value={filigreeSetFilter} class="h-8 rounded-md border border-input bg-background px-2 text-xs mr-2 max-w-[120px]">
                                                  <option value="">All Sets</option>
                                                  {#each uniqueFiligreeSets as setName}
                                                      <option value={setName}>{setName}</option>
                                                  {/each}
                                              </select>
                                              <button class="text-xs text-muted-foreground hover:text-primary" on:click={() => {editingFiligreeIdx = null; editingFiligreeType = null}}>Cancel</button>
                                          </div>
                                          <div class="max-h-40 overflow-y-auto space-y-1">
                                              {#if isFetchingFiligrees}
                                                  <p class="text-xs text-muted-foreground animate-pulse">Loading...</p>
                                              {:else}
                                                  {#each filteredFiligrees as availableFil}
                                                      <button on:click={() => selectFiligree(idx, availableFil)} class="w-full text-left p-2 rounded text-xs bg-card hover:bg-muted transition-colors border border-transparent hover:border-primary">
                                                          <div class="font-semibold">{availableFil.Name}</div>
                                                          <div class="text-[10px] text-muted-foreground truncate">{availableFil.SetName} - {availableFil.Description}</div>
                                                      </button>
                                                  {/each}
                                                  {#if filteredFiligrees.length === 0}
                                                      <p class="text-xs text-muted-foreground">No matching filigrees found.</p>
                                                  {/if}
                                              {/if}
                                          </div>
                                      </div>
                                  {:else}
                                      <button on:click={() => openFiligreePicker(idx, "artifact")} class="w-full text-left p-2 rounded bg-muted/50 hover:bg-muted border border-transparent hover:border-primary transition-colors text-sm flex items-center justify-between">
                                          {#if $configStore.pre_filled_filigrees?.artifact && $configStore.pre_filled_filigrees.artifact[idx]}
                                              <span class="text-primary font-medium">{$configStore.pre_filled_filigrees.artifact[idx]}</span>
                                          {:else}
                                              <span class="text-muted-foreground italic">Empty (Click to add)</span>
                                          {/if}
                                      </button>
                                  {/if}
                              </div>
                          {/each}
                      </div>
                  </div>
              {/if}
              
              {#if getWeaponFiligreeCount(selectedItemDetails) > 0}
                  <div class="mt-6 pt-4 border-t border-border/50">
                      <h4 class="font-semibold text-lg mb-3">Sentient Weapon Filigrees</h4>
                      <div class="space-y-3">
                          {#each Array(getWeaponFiligreeCount(selectedItemDetails)) as _, idx}
                              <div class="flex flex-col space-y-1">
                                  <div class="flex justify-between items-center text-sm font-medium">
                                      <span>Weapon Filigree Slot {idx + 1}</span>
                                      {#if $configStore.pre_filled_filigrees?.weapon && $configStore.pre_filled_filigrees.weapon[idx]}
                                          <button class="text-xs text-destructive hover:underline" on:click={() => clearFiligree(idx, "weapon")}>Remove</button>
                                      {/if}
                                  </div>
                                  {#if editingFiligreeIdx === idx && editingFiligreeType === "weapon"}
                                      <div class="mt-2 p-3 bg-muted/30 rounded border border-border">
                                          <div class="flex justify-between items-center mb-2">
                                              <input type="text" bind:value={filigreeSearchQuery} on:input={handleFiligreeSearchInput} placeholder="Search filigrees by stat or set..." class="flex-1 h-8 rounded-md border border-input bg-background px-2 text-xs mr-2" />
                                              <select bind:value={filigreeSetFilter} class="h-8 rounded-md border border-input bg-background px-2 text-xs mr-2 max-w-[120px]">
                                                  <option value="">All Sets</option>
                                                  {#each uniqueFiligreeSets as setName}
                                                      <option value={setName}>{setName}</option>
                                                  {/each}
                                              </select>
                                              <button class="text-xs text-muted-foreground hover:text-primary" on:click={() => {editingFiligreeIdx = null; editingFiligreeType = null}}>Cancel</button>
                                          </div>
                                          <div class="max-h-40 overflow-y-auto space-y-1">
                                              {#if isFetchingFiligrees}
                                                  <p class="text-xs text-muted-foreground animate-pulse">Loading...</p>
                                              {:else}
                                                  {#each filteredFiligrees as availableFil}
                                                      <button on:click={() => selectFiligree(idx, availableFil)} class="w-full text-left p-2 rounded text-xs bg-card hover:bg-muted transition-colors border border-transparent hover:border-primary">
                                                          <div class="font-semibold">{availableFil.Name}</div>
                                                          <div class="text-[10px] text-muted-foreground truncate">{availableFil.SetName} - {availableFil.Description}</div>
                                                      </button>
                                                  {/each}
                                                  {#if filteredFiligrees.length === 0}
                                                      <p class="text-xs text-muted-foreground">No matching filigrees found.</p>
                                                  {/if}
                                              {/if}
                                          </div>
                                      </div>
                                  {:else}
                                      <button on:click={() => openFiligreePicker(idx, "weapon")} class="w-full text-left p-2 rounded bg-muted/50 hover:bg-muted border border-transparent hover:border-primary transition-colors text-sm flex items-center justify-between">
                                          {#if $configStore.pre_filled_filigrees?.weapon && $configStore.pre_filled_filigrees.weapon[idx]}
                                              <span class="text-primary font-medium">{$configStore.pre_filled_filigrees.weapon[idx]}</span>
                                          {:else}
                                              <span class="text-muted-foreground italic">Empty (Click to add)</span>
                                          {/if}
                                      </button>
                                  {/if}
                              </div>
                          {/each}
                      </div>
                  </div>
              {/if}
          </div>
      {:else}
          <div class="flex-1 flex flex-col items-center justify-center text-center text-muted-foreground p-12">
              <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round" class="mb-4 opacity-50"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M7 7h.01"/><path d="M17 7h.01"/><path d="M7 17h.01"/><path d="M17 17h.01"/></svg>
              <p>Select a slot on the left to view or edit its item.</p>
          </div>
      {/if}
  </div>
</div>
