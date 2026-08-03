<script lang="ts">
  import { configStore, isOptimizing, resultStore, currentTab, showToast } from '$lib/store';
  import { RunOptimization, UpdateExternalSources } from '../../../../wailsjs/go/main/App';
  import { hydrateConfigFromSlots } from '../../store';
  import { onMount } from 'svelte';

  let newStatName = '';
  let newStatWeight = 100;
  let showExcludedPacks = false;
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

  function addStatPriority() {
    if (newStatName.trim()) {
      const name = newStatName.trim();
      const existingIdx = $configStore.stat_priorities.findIndex(e => e.stat === name);
      if (existingIdx >= 0) {
        $configStore.stat_priorities[existingIdx] = { stat: name, value: newStatWeight };
      } else {
        $configStore.stat_priorities = [...$configStore.stat_priorities, { stat: name, value: newStatWeight }];
      }
      newStatName = '';
      newStatWeight = 100;
    }
  }

  function handleStatKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') {
      addStatPriority();
    }
  }

  function editStatPriority(stat: string, weight: number) {
    newStatName = stat;
    newStatWeight = weight;
  }

  function removeStatPriority(key: string) {
    $configStore.stat_priorities = $configStore.stat_priorities.filter(e => e.stat !== key);
  }

  // Mirrors the filigree-selection allocation rule implemented in
  // python/optimizer.py (see docs/PHASE9_PLAN.md, Phase 9.1):
  //  - exactly one priority at 100 -> all weight to that stat
  //  - multiple priorities at 100 -> geometric decay (60/40, ~51/31/18, ...) in entry order
  //  - no 100s -> prorate every listed stat by its value's share of the total
  function computeFiligreeBias(priorities: { stat: string; value: number }[]): { stat: string; pct: number }[] {
    if (!priorities || priorities.length === 0) return [];
    const hundreds = priorities.filter(p => p.value >= 100);
    if (hundreds.length > 0) {
      const raw = hundreds.map((_, i) => 0.6 * Math.pow(0.4, i));
      const sum = raw.reduce((a, b) => a + b, 0);
      return hundreds.map((p, i) => ({ stat: p.stat, pct: Math.round((raw[i] / sum) * 1000) / 10 }));
    }
    const total = priorities.reduce((a, p) => a + p.value, 0);
    if (total <= 0) return [];
    return priorities.map(p => ({ stat: p.stat, pct: Math.round((p.value / total) * 1000) / 10 }));
  }

  $: filigreeBias = computeFiligreeBias($configStore.stat_priorities);

  async function handleOptimize() {
    $isOptimizing = true;
    try {
      const result = await RunOptimization($configStore);
      $resultStore = result;
      if (result.success) {
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
</script>

<div class="glass-panel p-6 space-y-6">
  <div class="space-y-2">
    <h2 class="text-xl font-semibold tracking-tight">Gear Optimization Configuration</h2>
    <p class="text-sm text-muted-foreground">Configure your character build and optimizer constraints.</p>
  </div>

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
      <label class="text-sm font-medium leading-none" for="raid-limit">Max Raid Items</label>
      <input id="raid-limit" type="number" bind:value={$configStore.raid_item_limit} class="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2" />
    </div>

    <div class="space-y-2">
      <label class="text-sm font-medium leading-none" for="armor-restriction">Armor Restriction</label>
      <select id="armor-restriction" bind:value={$configStore.armor_restriction} class="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
        <option value="Any" class="bg-background text-foreground">Any</option>
        <option value="Cloth" class="bg-background text-foreground">Cloth</option>
        <option value="Light" class="bg-background text-foreground">Light</option>
        <option value="Medium" class="bg-background text-foreground">Medium</option>
        <option value="Heavy" class="bg-background text-foreground">Heavy</option>
      </select>
    </div>

    <div class="space-y-2">
      <label class="text-sm font-medium leading-none" for="minor-artifact-slots">Minor Artifact Filigree Slots</label>
      <input id="minor-artifact-slots" type="number" bind:value={$configStore.minor_artifact_filigree_slots} class="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2" />
    </div>

    <div class="space-y-2">
      <label class="text-sm font-medium leading-none" for="reserved-minor-artifact">Reserved Minor Artifact Slot</label>
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

    <div class="space-y-2 flex flex-col justify-center pt-6">
      <label class="flex items-center space-x-2 text-sm cursor-pointer">
        <input type="checkbox" bind:checked={$configStore.is_dino_artifact} class="h-4 w-4 rounded border-input bg-transparent text-primary focus:ring-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background" />
        <span class="font-medium leading-none text-foreground">Dinosaur Bone Artifact</span>
      </label>
    </div>

    <div class="space-y-2 flex flex-col justify-center pt-6">
      <label class="flex items-center space-x-2 text-sm cursor-pointer">
        <input type="checkbox" bind:checked={$configStore.runearm_use} class="h-4 w-4 rounded border-input bg-transparent text-primary focus:ring-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background" />
        <span class="font-medium leading-none text-foreground">Runearm Use</span>
      </label>
    </div>

    <div class="space-y-2 flex flex-col justify-center pt-6">
      <label class="flex items-center space-x-2 text-sm cursor-pointer">
        <input type="checkbox" bind:checked={$configStore.exclude_gem_of_many_facets} class="h-4 w-4 rounded border-input bg-transparent text-primary focus:ring-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background" />
        <span class="font-medium leading-none text-foreground">Exclude Gem of Many Facets</span>
      </label>
    </div>
  </div>

  <div class="space-y-2 border-t border-border pt-4">
    <button class="flex items-center justify-between w-full text-left" on:click={() => showExcludedPacks = !showExcludedPacks}>
      <span class="text-sm font-medium leading-none">Excluded Expansion Packs</span>
      <span class="text-muted-foreground">{showExcludedPacks ? '▲' : '▼'}</span>
    </button>
    {#if showExcludedPacks}
      <div class="grid grid-cols-1 md:grid-cols-2 gap-2 mt-2">
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
    {/if}
  </div>

  <div class="space-y-2 border-t border-border pt-4">
    <label class="text-sm font-medium leading-none" for="stat-name">Stat Priorities (1-100)</label>
    <div class="flex flex-col space-y-2">
      <div class="flex space-x-2">
        <input 
          id="stat-name"
          type="text" 
          bind:value={newStatName}
          on:keydown={handleStatKeydown}
          placeholder="Stat (e.g. Constitution)"
          class="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        />
        <button on:click={addStatPriority} class="inline-flex items-center justify-center rounded-md text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 h-10 px-4 py-2 ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
          Save
        </button>
      </div>
      <div class="flex items-center space-x-3">
        <input 
          type="range" 
          bind:value={newStatWeight}
          on:keydown={handleStatKeydown}
          min="1"
          max="100"
          class="w-full accent-primary"
        />
        <span class="text-sm font-medium w-8 text-right">{newStatWeight}</span>
      </div>
    </div>
    {#if $configStore.stat_priorities && $configStore.stat_priorities.length > 0}
      <div class="grid grid-cols-2 gap-2 mt-3">
        {#each $configStore.stat_priorities as { stat, value } (stat)}
          <div class="flex justify-between items-center border border-border rounded-md px-3 py-2 text-sm bg-card text-card-foreground cursor-pointer hover:border-primary transition-colors" on:click={() => editStatPriority(stat, value)}>
            <span class="font-medium truncate mr-2" title={stat}>{stat}</span>
            <div class="flex items-center space-x-3">
              <span class="text-muted-foreground">{value}</span>
              <button class="text-destructive hover:text-destructive/80 focus:outline-none font-bold" on:click|stopPropagation={() => removeStatPriority(stat)} aria-label="Remove">&times;</button>
            </div>
          </div>
        {/each}
      </div>
    {/if}
    {#if filigreeBias.length > 0}
      <p class="text-xs text-muted-foreground mt-2">
        Filigree bias: {filigreeBias.map(b => `${b.pct}% ${b.stat}`).join(', ')}
      </p>
    {/if}
  </div>

  <button 
    on:click={handleOptimize}
    disabled={$isOptimizing}
    class="w-full inline-flex items-center justify-center rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 bg-primary text-primary-foreground hover:bg-primary/90 h-10 px-4 py-2 mt-6"
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
    class="w-full inline-flex items-center justify-center rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 bg-secondary text-secondary-foreground hover:bg-secondary/80 border border-border h-10 px-4 py-2 mt-4"
  >
    {#if isUpdatingData}
      <span class="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
      Updating...
    {:else}
      Update External Sources (DDOBuilderV2)
    {/if}
  </button>
</div>
