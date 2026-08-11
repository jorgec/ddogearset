<script lang="ts">
  import { resultStore, configStore, isOptimizing, hydrateConfigFromSlots, showToast } from '$lib/store';
  import { RunOptimization, SaveGearset, GetAppVersion, VerifyGearsetChecksum, GetSetBonus,
           ListBuilds, LoadBuild, ImportGearsetContent } from '../../../../wailsjs/go/main/App';
  import { onMount } from 'svelte';
  import type { appdb } from '../../../../wailsjs/go/models';
  // Imported as a VALUE (not `import type`) because createFrom is a static
  // method on the generated class, and the type-only import above cannot
  // reach it.
  import { main as mainModels } from '../../../../wailsjs/go/models';
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

  // A saved gearset's excluded_packs is matched server-side by EXACT string
  // against the real AdventurePack value (see python/optimizer.py's
  // parse_items) — a name that doesn't match exactly excludes nothing, silently.
  // "The Chill of Ravenloft" was briefly offered as a checkbox value before the
  // real pack name ("Chill of Ravenloft", no "The") was confirmed — any gearset
  // saved during that window carries the wrong string forever unless migrated
  // here. This is exactly the bug behind GitHub issue jorgec/ddogearset#1.
  const LEGACY_PACK_RENAMES: Record<string, string> = {
      'The Chill of Ravenloft': 'Chill of Ravenloft',
  };

  // Folds a legacy gearset's caster_spellpowers/caster_schools into Tier 1 and
  // clears them, so the migration runs exactly once per load rather than on
  // every reactive tick (docs/TIERED_SOLVER_FRONTEND_SPEC.md §5.3). Also
  // renames any known-stale excluded_packs entries to their real pack name.
  function migrateLegacyConfig(config: main.OptimizationPayload): main.OptimizationPayload {
      const { priorities, migrated } = migrateLegacyCasterFields(
          config.stat_priorities,
          config.caster_spellpowers,
          config.caster_schools
      );
      if (migrated > 0) {
          showToast(`Imported ${migrated} caster stat(s) from a saved gearset into Tier 1.`, 'info');
      }

      let renamedPacks = 0;
      const excludedPacks = (config.excluded_packs ?? []).map((p) => {
          if (LEGACY_PACK_RENAMES[p]) {
              renamedPacks++;
              return LEGACY_PACK_RENAMES[p];
          }
          return p;
      });
      if (renamedPacks > 0) {
          showToast(
              `Corrected ${renamedPacks} excluded-pack name(s) from this saved gearset ` +
              `that didn't match the real pack name and were excluding nothing.`,
              'info'
          );
      }

      // Cast mirrors store.ts: the spread drops the wails class's convertValues
      // method, which nothing on this path calls.
      return {
          ...config,
          stat_priorities: priorities,
          caster_spellpowers: [],
          caster_schools: [],
          excluded_packs: excludedPacks,
      } as unknown as main.OptimizationPayload;
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

  // --- Set-bonus pips (docs/DASHBOARD_REDESIGN_SPEC.md §4.3) ---------------
  // "Do not just list them. Use small graphical pips (e.g. 2/3 lit pips) to
  // quickly show how many pieces of a set are active." The active count is in
  // the solver's own "Name (N-piece)" string; the TOTAL is not, so it's looked
  // up from the set definition's own tier list (the highest EquippedCount any
  // tier requires) and cached per set name. A set whose definition can't be
  // resolved falls back to total == active, i.e. all pips lit — never a
  // fabricated denominator.
  let setTierMax: Record<string, number> = {};

  function parseActiveSet(s: string): { name: string; active: number } {
      const m = (s || '').match(/^(.*?)\s*\((\d+)[-\s]?piece\)$/i);
      return m ? { name: m[1].trim(), active: parseInt(m[2], 10) } : { name: s, active: 0 };
  }

  async function loadSetTierMax(names: string[]) {
      for (const n of names) {
          if (!n || n in setTierMax) continue;
          setTierMax[n] = 0; // claim the key before awaiting so a re-run can't double-fetch
          try {
              const sb: any = await GetSetBonus(n);
              const counts = (sb?.Tiers ?? [])
                  .map((t: any) => parseInt(t.EquippedCount, 10))
                  .filter((v: number) => !isNaN(v));
              setTierMax[n] = counts.length ? Math.max(...counts) : 0;
              setTierMax = { ...setTierMax };
          } catch {
              /* leave 0 — the pip row falls back to active-count-only */
          }
      }
  }

  // `activeSets` lists every active TIER, not every set — a 4-piece Zarigan's
  // shows up three times as "(2-piece)", "(3-piece)" and "(4-piece)". Rendering
  // one pip row per entry would claim three separate sets. Collapse to one row
  // per set at its highest active tier, which is what "how many pieces of a set
  // are active" actually means.
  $: activeSetRows = (() => {
      const byName = new Map<string, number>();
      for (const s of ($resultStore?.activeSets ?? [])) {
          const { name, active } = parseActiveSet(s);
          byName.set(name, Math.max(byName.get(name) ?? 0, active));
      }
      return [...byName.entries()].map(([name, active]) => ({ name, active }));
  })();
  $: loadSetTierMax(activeSetRows.map((r) => r.name));

  // Stored builds (app.db). The .ddogearset file is an EXPORT format from
  // 0.5.1 on — storage is the database, so this list, not the file picker, is
  // the normal way back to a gearset. Refreshed after every save and import
  // rather than kept live: saves are rare and a stale list is confusing.
  let builds: appdb.BuildSummary[] = [];
  let selectedBuild = '';

  async function refreshBuilds() {
      try {
          builds = await ListBuilds();
      } catch (e) {
          // Storage being unavailable is survivable — the app still solves.
          // Logged, not surfaced: an error toast on every mount for something
          // the user cannot act on is noise.
          console.error('Failed to list saved builds', e);
          builds = [];
      }
  }
  onMount(refreshBuilds);

  async function openBuild(uuid: string) {
      if (!uuid) return;
      $isOptimizing = true;
      try {
          const loaded = await LoadBuild(uuid);
          // createFrom, not a spread: the generated bindings are CLASSES, and a
          // plain object literal is not assignable to one. The file-picker path
          // below gets away with a spread only because JSON.parse gives it `any`.
          $configStore = migrateLegacyConfig(mainModels.OptimizationPayload.createFrom(
              { ...$configStore, ...loaded.config, calculate_only: false }));
          if (loaded.orphans?.length) {
              const names = loaded.orphans.map((o) => o.name).join(', ');
              showToast(
                  `This build references ${loaded.orphans.length} item(s) that are no longer ` +
                  `in the catalog: ${names}. Everything else loaded normally.`,
                  'info'
              );
          }
      } catch (e) {
          console.error(e);
          showToast('Failed to load build: ' + e, 'error');
          $isOptimizing = false;
          return;
      }
      // A stored build carries no stats by design — app.db records what you
      // configured and what you have equipped, and the numbers come from
      // recalculating them.
      $resultStore = null as any;
      $isOptimizing = false;
      await calculateStats();
      await refreshBuilds();
  }

  function loadGearset() {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = '.ddogearset,.json';
      input.onchange = (e) => {
          const file = (e.target as HTMLInputElement).files?.[0];
          if (!file) return;
          const reader = new FileReader();
          reader.onload = async (re) => {
              try {
                  const rawText = re.target?.result as string;

                  // Content-integrity check (docs: gearset_checksum.go) — a
                  // file saved before this feature existed simply has no
                  // checksum field at all (hasChecksum: false) and is not
                  // flagged; only a genuine mismatch (the content changed
                  // since it was saved — hand-edited, corrupted, etc.) warns.
                  // Never refuses to load, same "warn, don't block" policy as
                  // the app-version check below.
                  try {
                      const checksumResult = await VerifyGearsetChecksum(rawText);
                      if (checksumResult.hasChecksum && !checksumResult.valid) {
                          showToast(
                              "This gearset file's content does not match its saved checksum — " +
                              'it may have been modified outside the app since it was saved. ' +
                              'Loaded anyway, but double-check it before trusting it.',
                              'error'
                          );
                      }
                  } catch (e) {
                      console.error('Failed to verify gearset checksum', e);
                  }

                  // Loading a file is now an IMPORT: the build lands in
                  // app.db so it survives without the file, and the file stays
                  // exactly where the user keeps it. Failure here is reported
                  // but does not stop the load — being unable to persist should
                  // not stop someone looking at their own gearset.
                  try {
                      const outcome = await ImportGearsetContent(file.name, rawText);
                      if (outcome.status === 'imported') {
                          await refreshBuilds();
                      }
                  } catch (e) {
                      console.error('Failed to import gearset into storage', e);
                      showToast('Loaded, but could not save this to your builds: ' + e, 'error');
                  }

                  const data = JSON.parse(rawText);
                  if (data.config && data.result) {
                      // Full format: hydrate both config params and result
                      const loadedConfig = {...$configStore, ...data.config, calculate_only: false};
                      $configStore = migrateLegacyConfig(loadedConfig);
                      $resultStore = data.result;

                      // Warn (never refuse) on an app-version mismatch — a
                      // missing app_version means the file predates this check
                      // entirely (every gearset saved before this feature),
                      // not a real conflict, so it's treated the same as a
                      // genuine mismatch: a non-blocking notice with a button
                      // to re-save under the current version. "Update" just
                      // re-saves the now-migrated config/result (SaveGearset
                      // always writes a new timestamped file — nothing here
                      // overwrites the original on disk).
                      try {
                          const currentVersion = await GetAppVersion();
                          const savedVersion = data.app_version as string | undefined;
                          if (savedVersion !== currentVersion) {
                              const desc = savedVersion
                                  ? `saved with version ${savedVersion}`
                                  : 'saved before version tracking existed';
                              showToast(
                                  `This gearset was ${desc} — you're running ${currentVersion}. ` +
                                  `Fixes since then (e.g. excluded-pack name corrections) may not be reflected.`,
                                  'info',
                                  [{ label: 'Update Saved File', onClick: () => saveGearset() }]
                              );
                          }
                      } catch (e) {
                          console.error('Failed to check app version', e);
                      }
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
          await refreshBuilds();
          showToast('Saved. Exported a copy to ' + path, 'success');
      } catch (e) {
          console.error(e);
          showToast('Failed to save gearset: ' + e, 'error');
      }
  }
</script>

<div class="vellum h-full flex flex-col overflow-y-auto p-4 space-y-4">
  <div class="shrink-0">
      <div class="flex items-center justify-between gap-3 flex-wrap">
          <h2 class="panel-title text-sm">Vellum Summary Scroll</h2>
          <div class="flex items-center gap-1.5">
            <input id="gearset-name-input" type="text" bind:value={$configStore.gearset_name}
                   class="w-32 rounded border border-carved bg-void/50 px-2 py-1 text-xs text-vellum placeholder:text-steel/50 focus:outline-none focus:ring-1 focus:ring-ring"
                   placeholder="Gearset name" />
            {#if builds.length}
              <select bind:value={selectedBuild} disabled={$isOptimizing}
                      on:change={() => openBuild(selectedBuild)}
                      title="Open a saved build"
                      class="w-36 rounded border border-carved bg-void/50 px-2 py-1 text-[11px] text-vellum focus:outline-none focus:ring-1 focus:ring-ring">
                <option value="">Saved builds…</option>
                {#each builds as b (b.uuid)}
                  <option value={b.uuid}>{b.name}{b.orphanCount ? ' (!)' : ''}</option>
                {/each}
              </select>
            {/if}
            <button on:click={loadGearset} disabled={$isOptimizing}
                    class="px-2 py-1 text-[11px] rounded border border-carved bg-carved/60 text-vellum hover:bg-carved hover:shadow-press transition-all disabled:opacity-50 flex items-center gap-1">
                {#if $isOptimizing}
                    <span class="h-2.5 w-2.5 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
                {/if}
                Load
            </button>
            <button on:click={saveGearset} disabled={$isOptimizing}
                    class="px-2 py-1 text-[11px] rounded bg-arcane text-white hover:bg-arcane/85 transition-colors disabled:opacity-50">Save</button>
          </div>
      </div>
      <p class="text-[11px] text-steel mt-1">A complete overview of all prioritized and granted effects.</p>
      <div class="gold-rule my-3"></div>
  </div>

  {#if !$resultStore || !$resultStore.success || !Object.keys($resultStore.gearSet || {}).length}
      <div class="flex flex-col items-center justify-center h-64 text-center">
          <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round" class="text-muted-foreground mb-4 opacity-50"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/></svg>
          <h3 class="text-lg font-medium text-foreground">No Gearset Computed</h3>
          <p class="text-sm text-muted-foreground max-w-sm mt-1">Run the auto-solver or load a layout in the Gearset Editor to view the breakdown.</p>
      </div>
  {:else}
      <!-- Active Sets and Filigrees Summary -->
      <div class="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {#if activeSetRows.length > 0}
          <div>
              <h4 class="panel-title text-xs mb-2">Active Set Bonuses</h4>
              <ul class="space-y-1">
                  {#each activeSetRows as row}
                      {@const total = setTierMax[row.name] || row.active}
                      <li class="flex items-start gap-2">
                          <span class="flex gap-[3px] pt-[5px] shrink-0" aria-hidden="true">
                              {#each Array(total) as _, i}
                                  <span class="pip {i < row.active ? 'pip-lit' : 'pip-dim'}"></span>
                              {/each}
                          </span>
                          <span class="text-xs text-vellum leading-snug">
                              {row.name}
                              <span class="text-steel">({row.active}/{total})</span>
                          </span>
                      </li>
                  {/each}
              </ul>
          </div>
          {/if}

          {#if $resultStore.filigrees && ( ($resultStore.filigrees.weapon && $resultStore.filigrees.weapon.length > 0) || ($resultStore.filigrees.artifact && $resultStore.filigrees.artifact.length > 0) )}
          <!-- §4.3 — filigrees grouped tightly, smaller type, to save vertical space. -->
          <div>
              <h4 class="panel-title text-xs mb-2">Granted Filigrees</h4>
              {#if $resultStore.filigrees.weapon && $resultStore.filigrees.weapon.length > 0}
                  <div class="mb-2">
                      <span class="text-[10px] font-semibold text-steel uppercase tracking-wider">Weapon</span>
                      <ul class="text-[11px] leading-snug text-vellum/90">
                          {#each $resultStore.filigrees.weapon as f}
                              <li class="truncate" title={f}>{f}</li>
                          {/each}
                      </ul>
                  </div>
              {/if}
              {#if $resultStore.filigrees.artifact && $resultStore.filigrees.artifact.length > 0}
                  <div>
                      <span class="text-[10px] font-semibold text-steel uppercase tracking-wider">Minor Artifact</span>
                      <ul class="text-[11px] leading-snug text-vellum/90">
                          {#each $resultStore.filigrees.artifact as f}
                              <li class="truncate" title={f}>{f}</li>
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
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
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
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-5">
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
