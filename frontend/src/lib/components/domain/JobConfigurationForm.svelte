<script lang="ts">
  // Thin layout/orchestrator for the solver form
  // (docs/TIERED_SOLVER_FRONTEND_SPEC.md §9). The stat-priority UI, the preset
  // picker and the collapsible chrome all live in their own components; this
  // file only arranges them and owns the submit action.
  //
  // The caster spellpower/school checkbox grid that used to live here is gone
  // entirely (§5), not hidden: caster_spellpowers/caster_schools are read
  // nowhere in the solver — they were purely a client-side mechanism that
  // auto-injected picks into stat_priorities, with a standing reactive sync
  // that could add but never remove. The fields stay on the payload struct for
  // old-file deserialization (INV-3), and old files are migrated into Tier 1
  // once at load time in Summary.svelte, but nothing writes them again.

  import { configStore, isOptimizing, resultStore, currentTab, showToast } from '$lib/store';
  import { RunOptimization, UpdateExternalSources } from '../../../../wailsjs/go/main/App';
  import { hydrateConfigFromSlots } from '../../store';
  import type { main } from '../../../../wailsjs/go/models';
  import { onMount } from 'svelte';
  import Accordion from '$lib/components/ui/Accordion.svelte';
  import StatPriorityEditor from './StatPriorityEditor.svelte';
  import StatSetPicker from './StatSetPicker.svelte';

  let isUpdatingData = false;
  let expansions: string[] = [];

  onMount(async () => {
    try {
      const res = await fetch('/expansions.json');
      const data = await res.json();
      expansions = data.expansions ?? [];
    } catch (e) {
      console.error('Failed to load expansions.json', e);
    }
  });

  function togglePack(pack: string) {
    if (!$configStore.excluded_packs) {
      $configStore.excluded_packs = [];
    }
    if ($configStore.excluded_packs.includes(pack)) {
      $configStore.excluded_packs = $configStore.excluded_packs.filter(p => p !== pack);
    } else {
      $configStore.excluded_packs = [...$configStore.excluded_packs, pack];
    }
  }

  async function handleOptimize() {
    $isOptimizing = true;
    try {
      // Per-call shallow copy rather than a store mutation, for the same reason
      // as the calculate path: mode is a property of THIS request, not state
      // every other store subscriber should observe mid-flight.
      // The cast mirrors store.ts: spreading a wails-generated class produces a
      // plain object without its convertValues method, which the generated
      // signature nominally requires but never calls on the request path.
      const result = await RunOptimization(
        { ...$configStore, mode: 'optimize' } as unknown as main.OptimizationPayload
      );
      if (result.success) {
        $resultStore = result;
        const hydrated = hydrateConfigFromSlots($configStore, result.slots);
        if (hydrated) {
            $configStore.pre_equipped = hydrated.pre_equipped;
            $configStore.pre_filled_augments = hydrated.pre_filled_augments;
            $configStore.pre_filled_filigrees = hydrated.pre_filled_filigrees;
        }
        showToast('Optimization complete.', 'success');
        $currentTab = 'editor';
      } else {
        showToast(result.errorMessage || 'Optimization failed.', 'error');
      }
    } catch (err) {
      console.error(err);
      showToast('Optimization failed: ' + err, 'error');
    } finally {
      $isOptimizing = false;
    }
  }

  async function handleUpdateData() {
    isUpdatingData = true;
    try {
      await UpdateExternalSources();
      showToast('Data updated successfully.', 'success');
    } catch (e) {
      showToast('Update failed: ' + e, 'error');
    } finally {
      isUpdatingData = false;
    }
  }

  // Helper for max_level (Character Level)
  $: characterLevel = $configStore.max_level || 34;
  function updateCharacterLevel(e: Event) {
    const target = e.target as HTMLInputElement;
    $configStore.max_level = parseInt(target.value) || 34;
  }

  $: {
    if ($configStore.build_type === 'Melee' || $configStore.build_type === 'Tank') {
      if (!['Two Weapon Fighting', 'Two Handed Fighting', 'Single Weapon Fighting', 'Sword and Board'].includes($configStore.weapon_style)) {
        $configStore.weapon_style = 'Two Weapon Fighting';
      }
    } else if ($configStore.build_type === 'Ranged') {
      if (!['Bow', 'Repeating Crossbow', 'Great Crossbow', 'Dual Crossbow', 'Thrown', 'Shuriken'].includes($configStore.weapon_style)) {
        $configStore.weapon_style = 'Bow';
      }
    } else if ($configStore.build_type === 'Caster') {
      if ($configStore.weapon_style !== 'None') {
        $configStore.weapon_style = 'None';
      }
    }
  }

  $: weaponStyles = $configStore.build_type === 'Ranged' ? ['Bow', 'Repeating Crossbow', 'Great Crossbow', 'Dual Crossbow', 'Thrown', 'Shuriken'] :
                    $configStore.build_type === 'Caster' ? ['None'] :
                    ['Two Weapon Fighting', 'Two Handed Fighting', 'Single Weapon Fighting', 'Sword and Board'];

  // Collapsed-state digests
  $: artifactSummary = `Reserved: ${$configStore.reserved_minor_artifact_slot || 'Any'} · ${$configStore.minor_artifact_filigree_slots ?? 0} filigree slots`;
  $: excludedSummary = `${$configStore.excluded_packs?.length ?? 0} excluded`;
  $: priorityCount = $configStore.stat_priorities?.length ?? 0;
  $: solverSummary = `${$configStore.max_search_time}s total`;

  // Post-solve feedback for the search-time slider: the concrete, actionable
  // signal for "you should raise this", sourced from the solver's own report
  // rather than a separate client-side computation.
  $: lastRunSeconds = $resultStore?.tierReport?.totalElapsedSeconds;
  $: hasUnprovenStage = ($resultStore?.tierReport?.stages ?? []).some((s) => !s.proven);
</script>

<div class="glass-panel p-6 space-y-6">
  <div class="space-y-2">
    <h2 class="text-xl font-semibold tracking-tight">Gear Optimization Configuration</h2>
    <p class="text-sm text-muted-foreground">Configure your character build and optimizer constraints.</p>
  </div>

  <!-- 1. Build Profile — always visible, never collapsible -->
  <div class="grid grid-cols-2 gap-4">
    <div class="space-y-2">
      <label class="text-sm font-medium leading-none" for="build-type">Build Type</label>
      <select id="build-type" bind:value={$configStore.build_type} class="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
        <option value="Melee" class="bg-background text-foreground">Melee</option>
        <option value="Ranged" class="bg-background text-foreground">Ranged</option>
        <option value="Caster" class="bg-background text-foreground">Caster</option>
        <option value="Tank" class="bg-background text-foreground">Tank</option>
      </select>
    </div>

    <div class="space-y-2">
      <label class="text-sm font-medium leading-none" for="weapon-style">Weapon Style</label>
      <select id="weapon-style" bind:value={$configStore.weapon_style} class="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
        {#each weaponStyles as style}
          <option value={style} class="bg-background text-foreground">{style}</option>
        {/each}
      </select>
    </div>

    {#if $configStore.weapon_style === 'Single Weapon Fighting'}
      <div class="space-y-2">
        <label class="text-sm font-medium leading-none" for="offhand-style">Offhand Style</label>
        <select id="offhand-style" bind:value={$configStore.offhand_style} class="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
          <option value="Empty" class="bg-background text-foreground">Empty Hand (no shield slot)</option>
          <option value="Orb" class="bg-background text-foreground">Orb</option>
          <option value="Buckler" class="bg-background text-foreground">Buckler</option>
          <option value="Runearm" class="bg-background text-foreground">Runearm</option>
        </select>
      </div>
    {/if}

    <div class="space-y-2">
      <label class="text-sm font-medium leading-none" for="char-level">Character Level</label>
      <input id="char-level" type="number" value={characterLevel} on:input={updateCharacterLevel} class="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2" />
    </div>

    <div class="space-y-2">
      <label class="text-sm font-medium leading-none" for="armor-restriction">Armor Restriction</label>
      <select id="armor-restriction" bind:value={$configStore.armor_restriction} class="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
        <option value="Any" class="bg-background text-foreground">Any</option>
        <option value="Cloth" class="bg-background text-foreground">Cloth</option>
        <option value="Light" class="bg-background text-foreground">Light</option>
        <option value="Medium" class="bg-background text-foreground">Medium</option>
        <option value="Heavy" class="bg-background text-foreground">Heavy</option>
        <option value="Docent" class="bg-background text-foreground">Docent</option>
      </select>
    </div>
  </div>

  <!-- 2. Stat Sets -->
  <Accordion title="Stat Sets" persistKey="stat-sets" summary="Presets">
    <StatSetPicker />
  </Accordion>

  <!-- 3. Stat Priorities — always open, deliberately no persistKey (§8.3):
       it is the primary input and must never silently start collapsed. -->
  <Accordion title="Stat Priorities" open={true} summary={`${priorityCount} stats`}>
    <StatPriorityEditor />
  </Accordion>

  <!-- 4. Equipment Constraints -->
  <Accordion title="Equipment Constraints" persistKey="equipment-constraints">
    <div class="grid grid-cols-2 gap-4">
      <div class="space-y-2">
        <label class="text-sm font-medium leading-none" for="raid-limit">Max Raid Items</label>
        <input id="raid-limit" type="number" bind:value={$configStore.raid_item_limit} class="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2" />
      </div>

      <div class="space-y-2 flex flex-col justify-center pt-6">
        <label class="flex items-center space-x-2 text-sm cursor-pointer">
          <input type="checkbox" bind:checked={$configStore.runearm_use} class="h-4 w-4 rounded border-input bg-transparent text-primary focus:ring-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background" />
          <span class="font-medium leading-none text-foreground">Runearm Use</span>
        </label>
      </div>

      <div class="space-y-2 flex flex-col justify-center">
        <label class="flex items-center space-x-2 text-sm cursor-pointer">
          <input type="checkbox" bind:checked={$configStore.exclude_gem_of_many_facets} class="h-4 w-4 rounded border-input bg-transparent text-primary focus:ring-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background" />
          <span class="font-medium leading-none text-foreground">Exclude Gem of Many Facets</span>
        </label>
      </div>
    </div>
  </Accordion>

  <!-- 5. Artifact Configuration -->
  <Accordion title="Artifact Configuration" persistKey="artifact-config" summary={artifactSummary}>
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 p-4 border border-border rounded-lg bg-card/20">
      <div class="space-y-2">
        <label class="text-sm font-medium leading-none" for="reserved-minor-artifact">Reserved Slot</label>
        <select id="reserved-minor-artifact" bind:value={$configStore.reserved_minor_artifact_slot} class="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
          <option value="" class="bg-background text-foreground">Any</option>
          <option value="Helmet" class="bg-background text-foreground">Helmet</option>
          <option value="Necklace" class="bg-background text-foreground">Necklace</option>
          <option value="Trinket" class="bg-background text-foreground">Trinket</option>
          <option value="Cloak" class="bg-background text-foreground">Cloak</option>
          <option value="Belt" class="bg-background text-foreground">Belt</option>
          <option value="Ring" class="bg-background text-foreground">Ring</option>
          <option value="Gloves" class="bg-background text-foreground">Gloves</option>
          <option value="Boots" class="bg-background text-foreground">Boots</option>
          <option value="Bracers" class="bg-background text-foreground">Bracers</option>
          <option value="Goggles" class="bg-background text-foreground">Goggles</option>
          <option value="Armor" class="bg-background text-foreground">Armor</option>
        </select>
      </div>
      <div class="space-y-2">
        <label class="text-sm font-medium leading-none" for="minor-artifact-slots">Filigree Slots</label>
        <input id="minor-artifact-slots" type="number" bind:value={$configStore.minor_artifact_filigree_slots} class="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2" />
      </div>
      <div class="flex items-center pt-6">
        <label class="flex items-center space-x-2 text-sm cursor-pointer">
          <input type="checkbox" bind:checked={$configStore.is_dino_artifact} class="h-4 w-4 rounded border-input bg-transparent text-primary focus:ring-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background" />
          <span class="font-medium leading-none text-foreground">Dinosaur Bone Artifact</span>
        </label>
      </div>
    </div>
  </Accordion>

  <!-- 6. Content Filters -->
  <Accordion title="Excluded Expansion Packs" persistKey="content-filters" summary={excludedSummary}>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
      {#each expansions as pack}
        <label class="flex items-center space-x-2 text-sm cursor-pointer">
          <input
            type="checkbox"
            checked={$configStore.excluded_packs?.includes(pack) ?? false}
            on:change={() => togglePack(pack)}
            class="h-4 w-4 rounded border-input bg-transparent text-primary focus:ring-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background"
          />
          <span class="text-foreground">{pack}</span>
        </label>
      {/each}
    </div>
  </Accordion>

  <!-- 7. Solver Settings -->
  <Accordion title="Solver Settings" persistKey="solver-settings" summary={solverSummary}>
    <div class="space-y-2">
      <label class="text-sm font-medium leading-none" for="search-time">
        Total Search Time (seconds — across all solve stages)
      </label>
      <div class="flex items-center space-x-3">
        <input
          id="search-time"
          type="range"
          min="10"
          max="600"
          step="5"
          bind:value={$configStore.max_search_time}
          class="w-full accent-primary"
        />
        <span class="text-sm font-medium w-10 text-right">{$configStore.max_search_time}</span>
      </div>
      <p class="text-[10px] text-muted-foreground">
        Split across up to five tier stages plus a consolidation pass. Longer budgets help most
        when you use many tiers. The backend clamps this to a hard ceiling of 1800 seconds.
      </p>
      {#if lastRunSeconds !== undefined}
        <p class="text-[10px] {hasUnprovenStage ? 'text-amber-500' : 'text-muted-foreground'}">
          Last run: {lastRunSeconds.toFixed(1)}s of {$configStore.max_search_time}s budget{hasUnprovenStage ? ' — a stage hit its time limit before proving optimality.' : '.'}
        </p>
      {/if}
    </div>
  </Accordion>

  <!-- Actions — always visible, so they stay reachable regardless of which
       sections are expanded. -->
  <div class="sticky bottom-0 -mx-6 -mb-6 px-6 py-4 bg-background/80 backdrop-blur border-t border-border space-y-3">
    <button
      on:click={handleOptimize}
      disabled={$isOptimizing}
      class="w-full inline-flex items-center justify-center rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 bg-primary text-primary-foreground hover:bg-primary/90 h-10 px-4 py-2"
    >
      {#if $isOptimizing}
        <span class="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
        Running Optimization...
      {:else}
        Optimize Gear
      {/if}
    </button>

    <button
      on:click={handleUpdateData}
      disabled={isUpdatingData}
      class="w-full inline-flex items-center justify-center rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 bg-secondary text-secondary-foreground hover:bg-secondary/80 border border-border h-10 px-4 py-2"
    >
      {#if isUpdatingData}
        <span class="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
        Updating...
      {:else}
        Update External Sources (DDOBuilderV2)
      {/if}
    </button>
  </div>
</div>
