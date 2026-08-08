<script lang="ts">
  import { onMount } from 'svelte';
  import JobConfigurationForm from '$lib/components/domain/JobConfigurationForm.svelte';
  import GearsetEditor from '$lib/components/domain/GearsetEditor.svelte';
  import FiligreeEditor from '$lib/components/domain/FiligreeEditor.svelte';
  import Summary from '$lib/components/domain/Summary.svelte';
  import ItemSearch from '$lib/components/domain/ItemSearch.svelte';
  import OwnedItems from '$lib/components/domain/OwnedItems.svelte';
  import StatusConsole from '$lib/components/domain/StatusConsole.svelte';
  import Toast from '$lib/components/domain/Toast.svelte';
  import { ParseMetadata } from '../wailsjs/go/main/App';
  import { isParsing, currentTab } from '$lib/store';
  import logoUrl from './assets/images/logo.jpg';

  onMount(async () => {
    // Optionally trigger an initial parse if needed based on Phase 4 Spec
    $isParsing = true;
    try {
      await ParseMetadata('data/metadata.xml');
    } catch (e) {
      console.error(e);
    } finally {
      $isParsing = false;
    }
  });
</script>

<main class="min-h-screen bg-slate-50 dark:bg-slate-950 p-4 md:p-8 flex flex-col space-y-6">
  <!-- Header -->
  <header class="glass-panel px-6 py-4 flex items-center justify-between sticky top-0 z-10">
    <div class="flex items-center space-x-3">
      <div class="p-1 rounded-md overflow-hidden">
        <img src={logoUrl} alt="DDO Gear Optimizer logo" class="h-8 w-8 rounded-sm object-cover" />
      </div>
      <div>
        <h1 class="text-xl font-bold tracking-tight">DDO Gear Optimizer</h1>
        <p class="text-xs text-muted-foreground">Go + Python + Svelte Architecture</p>
      </div>
    </div>
    <div class="flex items-center space-x-2">
      <button on:click={() => $currentTab = 'solver'} class="px-4 py-2 text-sm font-medium rounded-md transition-colors {$currentTab === 'solver' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'}">Auto-Solver</button>
      <button on:click={() => $currentTab = 'editor'} class="px-4 py-2 text-sm font-medium rounded-md transition-colors {$currentTab === 'editor' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'}">Gearset Editor</button>
      <button on:click={() => $currentTab = 'filigrees'} class="px-4 py-2 text-sm font-medium rounded-md transition-colors {$currentTab === 'filigrees' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'}">Filigrees</button>
      <button on:click={() => $currentTab = 'itemSearch'} class="px-4 py-2 text-sm font-medium rounded-md transition-colors {$currentTab === 'itemSearch' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'}">Item Search</button>
      <button on:click={() => $currentTab = 'ownedItems'} class="px-4 py-2 text-sm font-medium rounded-md transition-colors {$currentTab === 'ownedItems' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'}">Owned Items</button>
      <button on:click={() => $currentTab = 'summary'} class="px-4 py-2 text-sm font-medium rounded-md transition-colors {$currentTab === 'summary' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'}">Summary Breakdown</button>
    </div>
    
    <div class="flex items-center space-x-4 text-sm font-medium">
      {#if $isParsing}
        <span class="flex items-center text-amber-500">
          <span class="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
          Parsing XML...
        </span>
      {:else}
        <span class="flex items-center text-green-600 dark:text-green-500">
          <span class="relative flex h-3 w-3 mr-2">
            <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
            <span class="relative inline-flex rounded-full h-3 w-3 bg-green-500"></span>
          </span>
          System Ready
        </span>
      {/if}
    </div>
  </header>

  <!-- Main Content Area -->
  <div class="flex-1 overflow-hidden relative flex flex-col">
    {#if $currentTab === 'solver'}
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 h-full flex-1">
      <!-- Left Column: Config (2/3 width once side-by-side) -->
      <div class="lg:col-span-2 flex flex-col space-y-6">
        <JobConfigurationForm />
      </div>

      <!-- Right Column: Status Console (1/3 width once side-by-side) -->
      <div class="lg:col-span-1 flex flex-col space-y-6">
        <StatusConsole />
      </div>
    </div>
    {:else if $currentTab === 'editor'}
      <div class="h-full flex-1">
        <GearsetEditor />
      </div>
    {:else if $currentTab === 'filigrees'}
      <div class="h-full flex-1">
        <FiligreeEditor />
      </div>
    {:else if $currentTab === 'summary'}
      <div class="h-full flex-1">
        <Summary />
      </div>
    {:else if $currentTab === 'itemSearch'}
      <div class="h-full flex-1">
        <ItemSearch />
      </div>
    {:else if $currentTab === 'ownedItems'}
      <div class="h-full flex-1">
        <OwnedItems />
      </div>
    {/if}
  </div>
</main>

<Toast />

<style>
  :global(body) {
    overflow-x: hidden;
  }
</style>
