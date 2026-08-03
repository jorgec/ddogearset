<script lang="ts">
  import { resultStore, configStore, isOptimizing } from '$lib/store';
  import { RunOptimization, SaveGearset } from '../../../../wailsjs/go/main/App';
  
  // Sort priority stats based on their weight (descending)
  $: sortedPriorities = Object.entries($configStore.stat_priorities)
      .sort(([, weightA], [, weightB]) => weightB - weightA);

  // Group all effects by their stat name, then sort alphabetically
  $: groupedEffects = $resultStore?.allEffects ? 
      Object.entries($resultStore.allEffects).sort(([statA], [statB]) => statA.localeCompare(statB)) : [];

  function loadGearset() {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = '.ddogearset,.json';
      input.onchange = (e) => {
          const file = (e.target as HTMLInputElement).files?.[0];
          if (!file) return;
          const reader = new FileReader();
          reader.onload = (re) => {
              try {
                  const data = JSON.parse(re.target?.result as string);
                  if (data.config && data.result) {
                      // Full format: hydrate both config params and result
                      const loadedConfig = {...$configStore, ...data.config, calculate_only: false};
                      $configStore = loadedConfig;
                      $resultStore = data.result;
                  } else if (data.gearSet) {
                      $resultStore = data;
                      $configStore.pre_equipped = {...data.gearSet};
                  } else {
                      // Legacy: plain slot map
                      $resultStore = { success: true, timeTaken: 0, gearSet: data, realizedStats: {}, activeSets: [], filigrees: {} };
                      $configStore.pre_equipped = {...data};
                  }
                  
                  calculateStats();
              } catch(e) {
                  console.error('Failed to parse gearset file');
              }
          };
          reader.readAsText(file);
      };
      input.click();
  }
  
  async function calculateStats() {
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
  
  async function saveGearset() {
      try {
          const path = await SaveGearset($configStore, $resultStore);
          alert("Saved successfully to " + path);
      } catch (e) {
          console.error(e);
          alert("Failed to save gearset: " + e);
      }
  }
</script>

<div class="h-full flex flex-col space-y-6 overflow-y-auto p-4 md:p-6 bg-background rounded-lg border border-border shadow-sm">
  <div class="flex items-center justify-between border-b border-border/50 pb-4">
      <div>
          <h2 class="text-2xl font-bold tracking-tight">Gearset Breakdown Summary</h2>
          <p class="text-sm text-muted-foreground mt-1">A complete overview of all prioritized and granted effects.</p>
      </div>
      <div class="flex items-center space-x-3">
          <div class="flex items-center space-x-2">
            <label for="gearset-name-input" class="text-sm font-medium text-muted-foreground whitespace-nowrap">Name:</label>
            <input id="gearset-name-input" type="text" bind:value={$configStore.gearset_name} class="w-36 rounded-md border-input bg-background px-3 py-1 text-sm border focus:border-primary focus:ring-primary h-8" placeholder="My Gearset" />
          </div>
          <button on:click={loadGearset} disabled={$isOptimizing} class="px-3 py-1 text-sm bg-muted text-muted-foreground hover:bg-muted/80 rounded transition-colors flex items-center">
              {#if $isOptimizing}
                  <span class="mr-1 h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
              {/if}
              Load
          </button>
          <button on:click={saveGearset} disabled={$isOptimizing} class="px-3 py-1 text-sm bg-primary text-primary-foreground hover:bg-primary/90 rounded transition-colors">Save Output</button>
      </div>
  </div>

  {#if !$resultStore || !$resultStore.success || !Object.keys($resultStore.gearSet || {}).length}
      <div class="flex flex-col items-center justify-center h-64 text-center">
          <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round" class="text-muted-foreground mb-4 opacity-50"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/></svg>
          <h3 class="text-lg font-medium text-foreground">No Gearset Computed</h3>
          <p class="text-sm text-muted-foreground max-w-sm mt-1">Run the auto-solver or load a layout in the Gearset Editor to view the breakdown.</p>
      </div>
  {:else}
      <!-- Active Sets and Filigrees Summary -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
          {#if $resultStore.activeSets && $resultStore.activeSets.length > 0}
          <div class="bg-muted/20 p-4 rounded-lg border border-border/50">
              <h4 class="font-semibold text-primary mb-3">Active Set Bonuses</h4>
              <ul class="list-disc pl-5 text-sm space-y-1 text-foreground">
                  {#each $resultStore.activeSets as set}
                      <li>{set}</li>
                  {/each}
              </ul>
          </div>
          {/if}

          {#if $resultStore.filigrees && ( ($resultStore.filigrees.weapon && $resultStore.filigrees.weapon.length > 0) || ($resultStore.filigrees.artifact && $resultStore.filigrees.artifact.length > 0) )}
          <div class="bg-muted/20 p-4 rounded-lg border border-border/50">
              <h4 class="font-semibold text-primary mb-3">Granted Filigrees</h4>
              {#if $resultStore.filigrees.weapon && $resultStore.filigrees.weapon.length > 0}
                  <div class="mb-2">
                      <span class="text-xs font-semibold text-muted-foreground uppercase">Weapon</span>
                      <ul class="list-disc pl-5 text-sm space-y-1 text-foreground">
                          {#each $resultStore.filigrees.weapon as f}
                              <li>{f}</li>
                          {/each}
                      </ul>
                  </div>
              {/if}
              {#if $resultStore.filigrees.artifact && $resultStore.filigrees.artifact.length > 0}
                  <div>
                      <span class="text-xs font-semibold text-muted-foreground uppercase">Minor Artifact</span>
                      <ul class="list-disc pl-5 text-sm space-y-1 text-foreground">
                          {#each $resultStore.filigrees.artifact as f}
                              <li>{f}</li>
                          {/each}
                      </ul>
                  </div>
              {/if}
          </div>
          {/if}
      </div>

      <div class="h-px bg-border/50 w-full my-4"></div>

      <!-- Priorities Section -->
      <section class="space-y-4">
          <h3 class="text-lg font-semibold flex items-center text-primary">
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="mr-2"><path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/></svg>
              Optimized Priority Targets
          </h3>
          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {#each sortedPriorities as [stat, weight], i}
                  <div class="p-4 rounded-lg bg-card border border-border relative overflow-hidden group hover:border-primary/50 transition-colors">
                      <div class="absolute top-0 right-0 w-16 h-16 bg-primary/10 rounded-bl-full -z-10 transition-transform group-hover:scale-110"></div>
                      <div class="text-xs text-muted-foreground font-medium mb-1 uppercase tracking-wider flex justify-between">
                          <span>Priority #{i+1}</span>
                          <span class="text-primary/70">W: {weight}</span>
                      </div>
                      <div class="text-base font-semibold leading-tight mb-2 text-foreground pr-4 truncate" title={stat}>{stat}</div>
                      <div class="text-2xl font-bold text-primary">
                          {$resultStore.realizedStats?.[stat] ?? 0}
                      </div>
                  </div>
              {/each}
          </div>
      </section>

      <div class="h-px bg-border/50 w-full my-4"></div>

      <!-- All Effects Section -->
      <section class="space-y-4 flex-1">
          <h3 class="text-lg font-semibold flex items-center">
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="mr-2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
              All Granted Effects
          </h3>
          
          {#if groupedEffects.length === 0}
              <p class="text-sm text-muted-foreground italic">No effects data available. Did you run the optimizer?</p>
          {:else}
              <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-8">
                  {#each groupedEffects as [statName, sources]}
                      <div class="flex flex-col space-y-2">
                          <h4 class="font-medium text-foreground text-sm border-b border-border/40 pb-1">{statName}</h4>
                          <ul class="space-y-1">
                              {#each sources as source}
                                  <li class="text-xs text-muted-foreground flex items-baseline">
                                      <span class="w-2 h-2 rounded-full bg-primary/40 mr-2 flex-shrink-0"></span>
                                      {source}
                                  </li>
                              {/each}
                          </ul>
                      </div>
                  {/each}
              </div>
          {/if}
      </section>
  {/if}
</div>
