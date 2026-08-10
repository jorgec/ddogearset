<script lang="ts">
  // Thin layout/orchestrator for the solver form
  // (docs/TIERED_SOLVER_FRONTEND_SPEC.md §9). The stat-priority UI, the preset
  // picker and the collapsible chrome all live in their own components; this
  // file only arranges them and owns the submit action.
  //
  // The OLD caster_spellpowers/caster_schools checkbox grid that used to live
  // here is still gone (§5) and those fields are still read nowhere in the
  // solver — they were a live reactive sync that could add a stat but never
  // remove it. CasterConfig.svelte (docs/HARD_REQUIRED_SLOTS_SPEC.md §4) is a
  // NEW, unrelated mechanism for the same rough idea (element/main-stat/
  // spell-school prefill) built the other way: a one-time "Apply" action that
  // writes into the same stat_priorities array the rest of this form already
  // uses, with no standing binding to go stale.

  import { configStore, isOptimizing, resultStore, drawerOpen, showToast, troveImportStore } from '$lib/store';
  import { RunOptimization } from '../../../../wailsjs/go/main/App';
  import { loadTroveCsv } from '$lib/services/troveImport';
  import { hydrateConfigFromSlots } from '../../store';
  import type { main } from '../../../../wailsjs/go/models';
  import { onMount } from 'svelte';
  import Accordion from '$lib/components/ui/Accordion.svelte';
  import StatPriorityEditor from './StatPriorityEditor.svelte';
  import StatSetPicker from './StatSetPicker.svelte';
  import CasterConfig from './CasterConfig.svelte';

  let expansions: string[] = [];

  // docs/TROVE_INVENTORY_IMPORT_SPEC.md — troveImportStore.ownedNames holds
  // everything LoadTroveInventory returned (survives the toggle being
  // switched off, and survives navigating away from this tab, and survives a
  // load triggered from the Owned Items screen instead — see store.ts);
  // restrictToOwned is the actual on/off switch. $configStore.owned_item_names
  // (what the solver sees) is empty unless BOTH a CSV has been loaded AND the
  // toggle is on — this is what keeps the restriction opt-in rather than a
  // standing mode that could silently activate with nothing behind it.
  let troveLoading = false;

  $: $configStore.owned_item_names = ($troveImportStore.restrictToOwned && $troveImportStore.ownedNames.length > 0)
    ? $troveImportStore.ownedNames
    : [];
  $: troveSummary = $troveImportStore.ownedNames.length > 0
    ? `${$troveImportStore.restrictToOwned ? 'On' : 'Off'} — ${$troveImportStore.ownedNames.length} names from ${$troveImportStore.fileName}`
    : 'Not loaded';

  function loadTroveInventory() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.csv';
    input.onchange = (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      troveLoading = true;
      const reader = new FileReader();
      reader.onload = async (re) => {
        try {
          const csvContent = re.target?.result as string;
          const result = await loadTroveCsv(csvContent, file.name);
          if (!result.success) {
            showToast('Failed to load Trove inventory: ' + (result.errorMessage || 'unknown error'), 'error');
            return;
          }
          showToast(`Loaded ${result.totalRows} rows, ${result.ownedNamesCount} owned item/augment names.`, 'success');
        } catch (e) {
          showToast('Failed to load Trove inventory: ' + e, 'error');
        } finally {
          troveLoading = false;
        }
      };
      reader.onerror = () => {
        troveLoading = false;
        showToast('Failed to read the selected file.', 'error');
      };
      reader.readAsText(file);
    };
    input.click();
  }

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
        // The gear sockets and vellum summary are always on screen now, so
        // there is no editor tab to jump to — collapsing the configuration
        // drawer is what reveals the result the user just asked for.
        $drawerOpen = false;
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

  // Helper for max_level (Character Level)
  $: characterLevel = $configStore.max_level || 34;
  function updateCharacterLevel(e: Event) {
    const target = e.target as HTMLInputElement;
    $configStore.max_level = parseInt(target.value) || 34;
  }

  // docs/HARD_REQUIRED_SLOTS_SPEC.md §4 — the caster weapon styles: Dual
  // Caster (both Weapon1/Weapon2 required, both one-handed), Stick and Orb
  // (Weapon1 one-handed + Weapon2 orb, both required), Stick and Runearm
  // (Weapon1 one-handed + Weapon2 runearm, both required), Crossbow and
  // Runearm (same as Stick and Runearm but Weapon1 is any crossbow type
  // instead of one-handed), Quarterstaff (locked to literal quarterstaff,
  // Weapon2 blocked), Two-Handed Weapon (docs/CASTER_WEAPON_SELECTION_SPEC.md
  // — broader two-handed pool: great sword/falchion/great axe/maul/great
  // club/quarterstaff plus all crossbow types with no runearm, Weapon2
  // blocked; covers items like Arctica/Caustica that Quarterstaff alone
  // couldn't reach), Any (fully unrestricted — no weapon_style-based type
  // narrowing on Weapon1 or Weapon2 at all, and Weapon2 is optional rather
  // than required; the solver picks whichever weapon/offhand combination
  // across every other style scores best). These are real weapon_style
  // values the backend already understands (python/solver.py's
  // resolve_weapon_lists) — unlike the old forced 'None', which gave casters
  // no Weapon2 slot at all.
  const CASTER_WEAPON_STYLES = ['Dual Caster', 'Stick and Orb', 'Stick and Runearm', 'Crossbow and Runearm', 'Quarterstaff', 'Two-Handed Weapon', 'Any'];
  const MELEE_WEAPON_STYLES = ['Two Weapon Fighting', 'Two Handed Fighting', 'Single Weapon Fighting', 'Sword and Board', 'Single Handed Weapon and Runearm'];

  // Styles whose Weapon2 is unconditionally a runearm — runearm_use is
  // auto-checked when one of these is selected so the UI reflects reality
  // (the backend doesn't read runearm_use for these styles at all; it's a
  // pure display/consistency nicety, not something that changes behavior).
  const RUNEARM_LOCKED_STYLES = ['Stick and Runearm', 'Crossbow and Runearm', 'Single Handed Weapon and Runearm'];
  $: if (RUNEARM_LOCKED_STYLES.includes($configStore.weapon_style) && !$configStore.runearm_use) {
    $configStore.runearm_use = true;
  }

  $: {
    if ($configStore.build_type === 'Melee' || $configStore.build_type === 'Tank') {
      if (!MELEE_WEAPON_STYLES.includes($configStore.weapon_style)) {
        $configStore.weapon_style = 'Two Weapon Fighting';
      }
    } else if ($configStore.build_type === 'Ranged') {
      if (!['Bow', 'Repeating Crossbow', 'Great Crossbow', 'Dual Crossbow', 'Thrown', 'Shuriken'].includes($configStore.weapon_style)) {
        $configStore.weapon_style = 'Bow';
      }
    } else if ($configStore.build_type === 'Caster') {
      if (!CASTER_WEAPON_STYLES.includes($configStore.weapon_style)) {
        $configStore.weapon_style = 'Dual Caster';
      }
    }
  }

  // weapon_damage_type only applies to Melee (docs/HARD_REQUIRED_SLOTS_SPEC.md
  // §1) — clear it when leaving Melee so a stale value from a prior build
  // doesn't silently keep restricting Weapon1 after the build type changes.
  $: if ($configStore.build_type !== 'Melee' && $configStore.weapon_damage_type) {
    $configStore.weapon_damage_type = '';
  }

  $: weaponStyles = $configStore.build_type === 'Ranged' ? ['Bow', 'Repeating Crossbow', 'Great Crossbow', 'Dual Crossbow', 'Thrown', 'Shuriken'] :
                    $configStore.build_type === 'Caster' ? CASTER_WEAPON_STYLES :
                    MELEE_WEAPON_STYLES;

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

<div class="space-y-1">

  <!-- 1. Build Profile — always visible, never collapsible -->
  <div class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
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

    {#if $configStore.build_type === 'Melee'}
      <div class="space-y-2">
        <label class="text-sm font-medium leading-none" for="weapon-damage-type">Weapon Damage Type</label>
        <select id="weapon-damage-type" bind:value={$configStore.weapon_damage_type} class="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
          <option value="" class="bg-background text-foreground">Any (no restriction)</option>
          <option value="Slashing" class="bg-background text-foreground">Slashing</option>
          <option value="Piercing" class="bg-background text-foreground">Piercing</option>
          <option value="Bludgeoning" class="bg-background text-foreground">Bludgeoning</option>
        </select>
        <p class="text-[10px] text-muted-foreground">
          When set, Weapon1 is restricted to this damage type from the five "craftable" weapon
          families (Dinosaur Bone, Undying Age, Legendary Green Steel, Viktranium Experiment
          crafting, Den of Vipers), falling back to any weapon of this damage type if none of
          those match (see docs/HARD_REQUIRED_SLOTS_SPEC.md).
        </p>
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

  <!-- 2b. Caster Configuration — docs/HARD_REQUIRED_SLOTS_SPEC.md §4 -->
  {#if $configStore.build_type === 'Caster'}
    <Accordion title="Caster Configuration" persistKey="caster-config" summary="Elements, main stat, schools">
      <CasterConfig />
    </Accordion>
  {/if}

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

  <!-- 6b. Owned Items (Trove Import) -->
  <Accordion title="Owned Items (Trove Import)" persistKey="trove-inventory" summary={troveSummary}>
    <div class="space-y-3">
      <p class="text-[10px] text-muted-foreground">
        Import a Trove inventory export (CSV) to restrict item/augment selection to
        gear you actually own. Only rows outside SharedCrafting with Binding of BtA or
        BtC are considered; names that don't exactly match DDOBuilderV2 are silently
        ignored — no filigree matching, no random-loot items (see
        docs/TROVE_INVENTORY_IMPORT_SPEC.md).
      </p>
      <div class="flex items-center space-x-4">
        <button
          type="button"
          on:click={loadTroveInventory}
          disabled={troveLoading}
          class="px-3 py-1.5 text-sm bg-secondary text-secondary-foreground hover:bg-secondary/80 rounded transition-colors disabled:opacity-50 shrink-0"
        >
          {troveLoading ? 'Loading...' : $troveImportStore.ownedNames.length > 0 ? 'Load a different CSV' : 'Load Trove CSV...'}
        </button>
        <label class="flex items-center space-x-2 text-sm" class:cursor-pointer={$troveImportStore.ownedNames.length > 0} class:opacity-40={$troveImportStore.ownedNames.length === 0}>
          <input
            type="checkbox"
            disabled={$troveImportStore.ownedNames.length === 0}
            bind:checked={$troveImportStore.restrictToOwned}
            class="h-4 w-4 rounded border-input bg-transparent text-primary focus:ring-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background disabled:cursor-not-allowed"
          />
          <span class="text-foreground">Only use items I own</span>
        </label>
      </div>
      {#if $troveImportStore.ownedNames.length > 0}
        <p class="text-[10px] text-muted-foreground">
          {$troveImportStore.fileName} — {$troveImportStore.totalRows} rows, {$troveImportStore.ownedNames.length} owned names
        </p>
      {/if}
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
        <p class="text-[10px] {hasUnprovenStage ? 'text-gold' : 'text-muted-foreground'}">
          Last run: {lastRunSeconds.toFixed(1)}s of {$configStore.max_search_time}s budget{hasUnprovenStage ? ' — a stage hit its time limit before proving optimality.' : '.'}
        </p>
      {/if}
    </div>
  </Accordion>

  <!-- Actions — always visible, so they stay reachable regardless of which
       sections are expanded. -->
  <div class="sticky bottom-0 -mx-3 px-3 py-3 bg-obsidian/95 backdrop-blur border-t border-carved flex flex-wrap gap-2">
    <button
      on:click={handleOptimize}
      disabled={$isOptimizing}
      class="w-full inline-flex items-center justify-center rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 bg-primary text-primary-foreground hover:bg-primary/90 h-9 px-6 py-2 flex-1 min-w-[12rem]"
    >
      {#if $isOptimizing}
        <span class="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
        Running Optimization...
      {:else}
        Optimize Gear
      {/if}
    </button>
  </div>
</div>
