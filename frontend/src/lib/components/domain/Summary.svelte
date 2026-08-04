<script lang="ts">
  import { resultStore, configStore, isOptimizing, hydrateConfigFromSlots, showToast } from '$lib/store';
  import { RunOptimization, SaveGearset } from '../../../../wailsjs/go/main/App';
  import TierReport from './TierReport.svelte';
  import Accordion from '../ui/Accordion.svelte';
  import { migrateLegacyCasterFields } from '$lib/data/statPriorities';
  import type { main } from '../../../../wailsjs/go/models';

  // Ordered by tier, then by array position within the tier — which IS the
  // intra-tier rank. The old sort keyed on `value`, a field the tiered model
  // no longer has; serialization already emits entries in exactly this order,
  // so this is a stable copy rather than a re-sort.
  $: sortedPriorities = ($configStore.stat_priorities ?? [])
      .map((p, i) => ({ stat: p.stat, tier: p.tier ?? 1, cap: p.cap, i }))
      .sort((a, b) => (a.tier - b.tier) || (a.i - b.i));

  // Folds a legacy gearset's caster_spellpowers/caster_schools into Tier 1 and
  // clears them, so the migration runs exactly once per load rather than on
  // every reactive tick (docs/TIERED_SOLVER_FRONTEND_SPEC.md §5.3).
  function migrateLegacyConfig(config: main.OptimizationPayload): main.OptimizationPayload {
      const { priorities, migrated } = migrateLegacyCasterFields(
          config.stat_priorities,
          config.caster_spellpowers,
          config.caster_schools
      );
      if (migrated > 0) {
          showToast(`Imported ${migrated} caster stat(s) from a saved gearset into Tier 1.`, 'info');
      }
      // Cast mirrors store.ts: the spread drops the wails class's convertValues
      // method, which nothing on this path calls.
      return { ...config, stat_priorities: priorities, caster_spellpowers: [], caster_schools: [] } as unknown as main.OptimizationPayload;
  }

  // Group all effects by their stat name, then sort alphabetically
  $: groupedEffects = $resultStore?.allEffects ? 
      Object.entries($resultStore.allEffects).sort(([statA], [statB]) => statA.localeCompare(statB)) : [];

  // Key of the currently expanded effect source (`${statName}::${index}`), or null if none expanded.
  let expandedSourceKey: string | null = null;

  // Extracts value, bonusType, and sourceName from an effect string like
  // "13.0 Enhancement (The Spring Equinox)" or a set-bonus string with nested
  // parens like "15.0 Artifact (Legendary Soul of the Red Dragon (2 Piece))".
  function parseEffectSource(raw: string): { value: number, bonusType: string, sourceName: string | null } {
      const match = raw.match(/^(-?[\d.]+)\s+([^\s]+)(?:\s+\((.+)\))?$/);
      if (match) {
          return {
              value: parseFloat(match[1]),
              bonusType: match[2],
              sourceName: match[3] || null
          };
      }
      return { value: 0, bonusType: 'Unknown', sourceName: null };
  }

  $: duplicatedStats = Object.entries($resultStore?.allEffects || {})
      .filter(([_, sources]) => Array.isArray(sources) && sources.length > 1)
      .map(([stat, sources]) => {
          return {
              stat,
              sources: (sources as string[]).map((raw: string) => {
                  const { value, bonusType, sourceName } = parseEffectSource(raw);
                  return { value, bonusType, sourceName, slot: locateSource(sourceName), raw };
              })
          };
      })
      .sort((a, b) => b.sources.length - a.sources.length);

  // Determines where in the gearset a given source name (item, augment, filigree,
  // or set bonus) comes from, so the user can see which equipped item/slot granted it.
  // Prefers the exact, structured resultStore.slots data (Phase 9.2) when present;
  // falls back to the older name-matching heuristic for gearsets saved before
  // that field existed.
  function locateSource(sourceName: string | null): string {
      if (!sourceName || !$resultStore) return 'Location unavailable';
      const slots = $resultStore.slots;

      if (slots) {
          for (const [slot, detail] of Object.entries(slots)) {
              if (detail.item?.name === sourceName) {
                  return `Equipped item — ${slot}`;
              }
              const aug = detail.augments?.find((a: any) => a.name === sourceName);
              if (aug) {
                  return `Augment on ${detail.item?.name} — ${slot}`;
              }
              const fil = detail.filigrees?.find((f: any) => f.name === sourceName);
              if (fil) {
                  return (slot === 'Weapon1' || slot === 'Weapon2')
                      ? `Sentient Weapon Filigree — ${slot}`
                      : `Minor Artifact Filigree — ${slot}`;
              }
              const setBonus = detail.set_bonus_contributions?.find((sb: any) => sourceName.startsWith(sb.set));
              if (setBonus) {
                  return `Active Set Bonus — ${setBonus.set} (${setBonus.pieces} Piece) via ${detail.item?.name} — ${slot}`;
              }
          }
      }

      const gearSet = $resultStore.gearSet || {};

      // Direct item match (equipped item name === source name)
      for (const [slot, itemName] of Object.entries(gearSet)) {
          if (itemName === sourceName) return `Equipped item — ${slot}`;
      }

      // Augment match: pre_filled_augments is keyed by slot -> color -> augment name
      // (older saved files may still have the legacy slot -> array-of-names shape).
      const preAugments = $configStore.pre_filled_augments || {};
      for (const [slot, augs] of Object.entries(preAugments)) {
          const names = Array.isArray(augs) ? augs : Object.values(augs || {});
          if ((names || []).includes(sourceName)) {
              const itemName = gearSet[slot];
              return itemName ? `Augment on ${itemName} — ${slot}` : `Augment — ${slot}`;
          }
      }

      // Sentient weapon filigree
      const weaponFiligrees = $resultStore.filigrees?.weapon || [];
      if (weaponFiligrees.some(f => f === sourceName || f.includes(sourceName))) {
          return 'Sentient Weapon Filigree';
      }

      // Minor artifact filigree
      const artifactFiligrees = $resultStore.filigrees?.artifact || [];
      if (artifactFiligrees.some(f => f === sourceName || f.includes(sourceName))) {
          return 'Minor Artifact Filigree';
      }

      // Set bonus: solver formats these source names as "Set Name (N Piece)"
      // (python/optimizer.py's create_model), which differs in punctuation/casing
      // from the "Set Name (N-piece)" strings in activeSets, so match structurally
      // instead of doing an exact/prefix string comparison against activeSets.
      const setMatch = sourceName.match(/^(.*) \(\d+ Piece\)$/i);
      if (setMatch) {
          return `Active Set Bonus — ${setMatch[1]}`;
      }

      return 'Location unavailable';
  }

  function toggleSourceDetail(key: string) {
      expandedSourceKey = expandedSourceKey === key ? null : key;
  }

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
                      $configStore = migrateLegacyConfig(loadedConfig);
                      $resultStore = data.result;
                  } else if (data.gearSet) {
                      $resultStore = data;
                      $configStore.pre_equipped = {...data.gearSet};
                  } else {
                      // Legacy: plain slot map
                      $resultStore = { success: true, timeTaken: 0, gearSet: data, realizedStats: {}, activeSets: [], filigrees: {} } as unknown as main.ResultPayload;
                      $configStore.pre_equipped = {...data};
                  }
                  
                  calculateStats();
              } catch(e) {
                  console.error('Failed to parse gearset file');
                  showToast('Failed to load gearset file: ' + e, 'error');
              }
          };
          reader.readAsText(file);
      };
      input.click();
  }
  
  async function calculateStats() {
      $isOptimizing = true;
      try {
          // Non-destructive/read-only recompute: hydrate pre_equipped/
          // pre_filled_augments/pre_filled_filigrees from the just-loaded
          // gearset's slots detail so calculate_only mode reflects exactly
          // what was loaded, instead of stripping anything not already in
          // configStore.pre_equipped. See docs/ENGINEERING.md "Known Issues".
          const hydrated = hydrateConfigFromSlots($configStore, $resultStore?.slots);
          if (hydrated) {
              $configStore.pre_equipped = hydrated.pre_equipped;
              $configStore.pre_filled_augments = hydrated.pre_filled_augments;
              $configStore.pre_filled_filigrees = hydrated.pre_filled_filigrees;
          }
          // Calculate mode travels on the request, not on the shared store —
          // see the matching note in GearsetEditor.calculateGearSet().
          const res = await RunOptimization(
              { ...$configStore, mode: 'calculate' } as unknown as main.OptimizationPayload
          );
          if (res && res.success) {
              $resultStore = res;
              showToast('Gearset loaded and stats recalculated.', 'success');
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
  
  async function saveGearset() {
      try {
          const path = await SaveGearset($configStore, $resultStore);
          showToast('Saved successfully to ' + path, 'success');
      } catch (e) {
          console.error(e);
          showToast('Failed to save gearset: ' + e, 'error');
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

      <!-- Renders nothing at all until a tiered solve has produced a report. -->
      <TierReport />

      <!-- Priorities Section -->
      <section class="space-y-4">
          <h3 class="text-lg font-semibold flex items-center text-primary">
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="mr-2"><path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/></svg>
              Optimized Priority Targets
          </h3>
          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {#each sortedPriorities as { stat, tier, cap }, i}
                  <div class="p-4 rounded-lg bg-card border border-border relative overflow-hidden group hover:border-primary/50 transition-colors">
                      <div class="absolute top-0 right-0 w-16 h-16 bg-primary/10 rounded-bl-full -z-10 transition-transform group-hover:scale-110"></div>
                      <div class="text-xs text-muted-foreground font-medium mb-1 uppercase tracking-wider flex justify-between">
                          <span>Priority #{i+1}</span>
                          <span class="text-primary/70">Tier {tier}{cap ? ` · cap ${cap}` : ''}</span>
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

      <!-- Duplicated Stats Section -->
      {#if duplicatedStats.length > 0}
      <section class="space-y-4">
          <h3 class="text-lg font-semibold flex items-center">
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="mr-2"><path d="M4 22h14a2 2 0 0 0 2-2V7.5L14.5 2H6a2 2 0 0 0-2 2v4"/><polyline points="14 2 14 8 20 8"/><path d="M2 15h10"/><path d="m9 18 3-3-3-3"/></svg>
              Duplicated Stat Sources
          </h3>
          <p class="text-sm text-muted-foreground italic mb-2">Stats fed by more than one equipped source — not necessarily wasted; Stacking-type bonuses are expected to have many.</p>
          
          <div class="space-y-0.5">
              {#each duplicatedStats as { stat, sources }}
                  <Accordion title="{stat} ({sources.length})">
                      <ul class="space-y-2 px-1 pb-2">
                          {#each sources as src}
                              <li class="text-sm flex flex-col space-y-0.5 border-l-2 border-primary/20 pl-3">
                                  <div class="text-foreground font-medium flex items-baseline space-x-1.5">
                                      <span class="text-primary">{src.value}</span>
                                      <span class="text-muted-foreground">{src.bonusType}</span>
                                      {#if src.sourceName}
                                          <span class="text-muted-foreground opacity-50">—</span>
                                          <span>{src.sourceName}</span>
                                      {/if}
                                  </div>
                                  <div class="text-xs text-muted-foreground italic">
                                      {src.slot}
                                  </div>
                              </li>
                          {/each}
                      </ul>
                  </Accordion>
              {/each}
          </div>
      </section>

      <div class="h-px bg-border/50 w-full my-4"></div>
      {/if}

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
                              {#each sources as source, idx}
                                  {@const key = `${statName}::${idx}`}
                                  <li class="text-xs">
                                      <button
                                          type="button"
                                          class="w-full text-left text-muted-foreground flex items-baseline hover:text-foreground transition-colors"
                                          on:click={() => toggleSourceDetail(key)}
                                          aria-expanded={expandedSourceKey === key}
                                      >
                                          <span class="w-2 h-2 rounded-full bg-primary/40 mr-2 flex-shrink-0"></span>
                                          {source}
                                      </button>
                                      {#if expandedSourceKey === key}
                                          <div class="ml-4 mt-0.5 text-[11px] text-primary/80 italic">
                                              {locateSource(parseEffectSource(source).sourceName)}
                                          </div>
                                      {/if}
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
