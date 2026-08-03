<script lang="ts">
  import { configStore, resultStore, isOptimizing } from '$lib/store';
  import { GetAvailableFiligrees, GetItemDetails } from '../../../../wailsjs/go/main/App';
  import { models } from '../../../../wailsjs/go/models';

  let editingFiligreeIdx: number | null = null;
  let editingFiligreeType: "weapon" | "artifact" | null = null;
  let availableFiligrees: models.XMLFiligree[] = [];
  let isFetchingFiligrees = false;
  let filigreeSearchQuery = "";
  let filigreeSearchTimeout: any;
  let filigreeSetFilter = "";

  let weaponSlots = 10;
  
  $: artifactSlots = $configStore?.minor_artifact_filigree_slots || 0;

  $: uniqueFiligreeSets = Array.from(new Set(availableFiligrees.map(f => f.SetName))).filter(Boolean).sort();
  $: filteredFiligrees = availableFiligrees.filter(f => !filigreeSetFilter || f.SetName === filigreeSetFilter);

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

  // Display value for a slot: 
  // It should show the pre-filled value if it exists, otherwise it shows the generator's chosen value.
  function getSlotDisplay(idx: number, type: "weapon" | "artifact") {
      if ($configStore.pre_filled_filigrees[type] && $configStore.pre_filled_filigrees[type][idx]) {
          return { name: $configStore.pre_filled_filigrees[type][idx], locked: true };
      }
      if ($resultStore?.filigrees && $resultStore.filigrees[type] && $resultStore.filigrees[type][idx]) {
          return { name: $resultStore.filigrees[type][idx], locked: false };
      }
      return null;
  }

</script>

<div class="h-full flex flex-col overflow-hidden bg-card text-card-foreground p-6 rounded-xl border border-border shadow-sm">
    <div class="mb-6">
        <h2 class="text-2xl font-bold tracking-tight">Sentient Filigrees</h2>
        <p class="text-sm text-muted-foreground mt-1">Manage filigrees for your equipped Minor Artifact and Sentient Weapon.</p>
    </div>

    <div class="flex-1 overflow-y-auto space-y-8 pr-2">
        {#if weaponSlots === 0 && artifactSlots === 0}
            <div class="flex flex-col items-center justify-center h-64 text-center">
                <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round" class="text-muted-foreground mb-4 opacity-50"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/></svg>
                <h3 class="text-lg font-medium text-foreground">No Sentient Items Equipped</h3>
                <p class="text-sm text-muted-foreground max-w-sm mt-1">Equip a Minor Artifact or a Level 20+ Weapon in the Gearset Editor to add filigrees.</p>
            </div>
        {/if}

        <!-- Minor Artifact Filigrees -->
        {#if artifactSlots > 0}
            <div class="bg-muted/20 p-5 rounded-lg border border-border/50">
                <h3 class="text-lg font-semibold mb-4 text-primary flex items-center">
                    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="mr-2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
                    Minor Artifact
                </h3>
                <div class="grid grid-cols-1 gap-3">
                    {#each Array(artifactSlots) as _, idx}
                        {@const display = getSlotDisplay(idx, "artifact")}
                        <div class="flex flex-col space-y-1">
                            <div class="flex justify-between items-center text-sm font-medium">
                                <span>Slot {idx + 1}</span>
                                {#if display?.locked}
                                    <button class="text-xs text-destructive hover:underline" on:click={() => clearFiligree(idx, "artifact")}>Unlock</button>
                                {/if}
                            </div>
                            
                            {#if editingFiligreeIdx === idx && editingFiligreeType === "artifact"}
                                <div class="mt-1 p-3 bg-muted/40 rounded border border-border">
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
                                <button on:click={() => openFiligreePicker(idx, "artifact")} class="w-full text-left p-2.5 rounded transition-colors text-sm flex items-center justify-between border {display?.locked ? 'bg-primary/10 border-primary/30 hover:border-primary' : (display ? 'bg-muted/40 border-border hover:border-primary/50' : 'bg-muted/10 border-dashed border-border hover:border-primary/50')}">
                                    {#if display}
                                        <span class="font-medium {display.locked ? 'text-primary' : 'text-foreground'}">
                                            {display.name}
                                            {#if display.locked}
                                                <span class="ml-2 text-[10px] px-1.5 py-0.5 rounded-full bg-primary/20 text-primary uppercase">Locked</span>
                                            {:else}
                                                <span class="ml-2 text-[10px] px-1.5 py-0.5 rounded-full bg-muted-foreground/20 text-muted-foreground uppercase">Auto</span>
                                            {/if}
                                        </span>
                                    {:else}
                                        <span class="text-muted-foreground italic">Empty (Click to lock a filigree)</span>
                                    {/if}
                                </button>
                            {/if}
                        </div>
                    {/each}
                </div>
            </div>
        {/if}

        <!-- Sentient Weapon Filigrees -->
        {#if weaponSlots > 0}
            <div class="bg-muted/20 p-5 rounded-lg border border-border/50">
                <h3 class="text-lg font-semibold mb-4 text-primary flex items-center">
                    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="mr-2"><path d="M14.5 17.5L3 6V3h3l11.5 11.5"/><path d="M13 19l6-6"/><path d="M16 16l4 4"/><path d="M19 21l2-2"/></svg>
                    Sentient Weapon
                </h3>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-3">
                    {#each Array(weaponSlots) as _, idx}
                        {@const display = getSlotDisplay(idx, "weapon")}
                        <div class="flex flex-col space-y-1">
                            <div class="flex justify-between items-center text-sm font-medium">
                                <span>Slot {idx + 1}</span>
                                {#if display?.locked}
                                    <button class="text-xs text-destructive hover:underline" on:click={() => clearFiligree(idx, "weapon")}>Unlock</button>
                                {/if}
                            </div>
                            
                            {#if editingFiligreeIdx === idx && editingFiligreeType === "weapon"}
                                <div class="mt-1 p-3 bg-muted/40 rounded border border-border">
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
                                <button on:click={() => openFiligreePicker(idx, "weapon")} class="w-full text-left p-2.5 rounded transition-colors text-sm flex items-center justify-between border {display?.locked ? 'bg-primary/10 border-primary/30 hover:border-primary' : (display ? 'bg-muted/40 border-border hover:border-primary/50' : 'bg-muted/10 border-dashed border-border hover:border-primary/50')}">
                                    {#if display}
                                        <span class="font-medium {display.locked ? 'text-primary' : 'text-foreground'}">
                                            {display.name}
                                            {#if display.locked}
                                                <span class="ml-2 text-[10px] px-1.5 py-0.5 rounded-full bg-primary/20 text-primary uppercase">Locked</span>
                                            {:else}
                                                <span class="ml-2 text-[10px] px-1.5 py-0.5 rounded-full bg-muted-foreground/20 text-muted-foreground uppercase">Auto</span>
                                            {/if}
                                        </span>
                                    {:else}
                                        <span class="text-muted-foreground italic">Empty (Click to lock a filigree)</span>
                                    {/if}
                                </button>
                            {/if}
                        </div>
                    {/each}
                </div>
            </div>
        {/if}
    </div>
</div>
