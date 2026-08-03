<script lang="ts">
  import { configStore, isOptimizing, resultStore } from '$lib/store';
  import { RunOptimization } from '../../../../wailsjs/go/main/App';
  
  let newStatName = '';
  let newStatWeight = 100;

  const expansions = [
    "Isle of Dread", 
    "Fables of the Feywild", 
    "Masterminds of Sharn", 
    "Mists of Ravenloft", 
    "Vecna Unleashed", 
    "Myth Drannor", 
    "Sinister Secret of Saltmarsh"
  ];

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
      $configStore.stat_priorities[newStatName.trim()] = newStatWeight;
      $configStore.stat_priorities = { ...$configStore.stat_priorities };
      newStatName = '';
      newStatWeight = 100;
    }
  }

  function removeStatPriority(key: string) {
    delete $configStore.stat_priorities[key];
    $configStore.stat_priorities = { ...$configStore.stat_priorities };
  }

  async function handleOptimize() {
    $isOptimizing = true;
    try {
      const result = await RunOptimization($configStore);
      $resultStore = result;
    } catch (err) {
      console.error(err);
      // In a real app we'd show a toast here
    } finally {
      $isOptimizing = false;
    }
  }

  // Helper for max_levels since it's an array but UI treats it as a single number (Character Level)
  $: characterLevel = $configStore.max_levels && $configStore.max_levels.length > 0 ? $configStore.max_levels[0] : 32;
  function updateCharacterLevel(e: Event) {
    const target = e.target as HTMLInputElement;
    $configStore.max_levels = [parseInt(target.value) || 32];
  }

  $: {
    if ($configStore.build_type === 'Melee' || $configStore.build_type === 'Tank') {
      if (!['Two Weapon Fighting', 'Two Handed Fighting', 'Single Weapon Fighting', 'Sword and Board'].includes($configStore.weapon_style)) {
        $configStore.weapon_style = 'Two Weapon Fighting';
      }
    } else if ($configStore.build_type === 'Ranged') {
      if (!['Bow', 'Crossbow', 'Thrown'].includes($configStore.weapon_style)) {
        $configStore.weapon_style = 'Bow';
      }
    } else if ($configStore.build_type === 'Caster') {
      if ($configStore.weapon_style !== 'None') {
        $configStore.weapon_style = 'None';
      }
    }
  }

  $: weaponStyles = $configStore.build_type === 'Ranged' ? ['Bow', 'Crossbow', 'Thrown'] : 
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

    <div class="space-y-2">
      <label class="text-sm font-medium leading-none" for="char-level">Character Level</label>
      <input id="char-level" type="number" value={characterLevel} on:input={updateCharacterLevel} class="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2" />
    </div>

    <div class="space-y-2">
      <label class="text-sm font-medium leading-none" for="raid-limit">Max Raid Items</label>
      <input id="raid-limit" type="number" bind:value={$configStore.raid_item_limit} class="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2" />
    </div>
  </div>

  <div class="space-y-2 border-t border-border pt-4">
    <label class="text-sm font-medium leading-none">Excluded Expansion Packs</label>
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
  </div>

  <div class="space-y-2 border-t border-border pt-4">
    <label class="text-sm font-medium leading-none" for="stat-name">Stat Priorities (1-100)</label>
    <div class="flex space-x-2">
      <input 
        id="stat-name"
        type="text" 
        bind:value={newStatName}
        placeholder="Stat (e.g. Constitution)"
        class="flex h-10 w-2/3 rounded-md border border-input bg-transparent px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      />
      <input 
        type="number" 
        bind:value={newStatWeight}
        min="1"
        max="100"
        class="flex h-10 w-1/3 rounded-md border border-input bg-transparent px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      />
      <button on:click={addStatPriority} class="inline-flex items-center justify-center rounded-md text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 h-10 px-4 py-2 ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
        Add
      </button>
    </div>
    {#if $configStore.stat_priorities && Object.keys($configStore.stat_priorities).length > 0}
      <div class="grid grid-cols-2 gap-2 mt-3">
        {#each Object.entries($configStore.stat_priorities) as [stat, weight]}
          <div class="flex justify-between items-center border border-border rounded-md px-3 py-2 text-sm bg-card text-card-foreground">
            <span class="font-medium">{stat}</span>
            <div class="flex items-center space-x-3">
              <span class="text-muted-foreground">{weight}</span>
              <button class="text-destructive hover:text-destructive/80 focus:outline-none font-bold" on:click={() => removeStatPriority(stat)} aria-label="Remove">&times;</button>
            </div>
          </div>
        {/each}
      </div>
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
</div>
