<script lang="ts">
  import { onMount } from 'svelte';
  import JobConfigurationForm from '$lib/components/domain/JobConfigurationForm.svelte';
  import ResultsDataGrid from '$lib/components/domain/ResultsDataGrid.svelte';
  import StatusConsole from '$lib/components/domain/StatusConsole.svelte';
  import { ParseMetadata } from '../wailsjs/go/main/App';
  import { isParsing } from '$lib/store';

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
      <div class="bg-primary text-primary-foreground p-2 rounded-md">
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-cpu"><rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9" rx="1"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/></svg>
      </div>
      <div>
        <h1 class="text-xl font-bold tracking-tight">DDO Gear Optimizer</h1>
        <p class="text-xs text-muted-foreground">Go + Python + Svelte Architecture</p>
      </div>
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
  <div class="grid grid-cols-1 lg:grid-cols-12 gap-6 flex-1">
    <!-- Left Column: Config -->
    <div class="lg:col-span-4 flex flex-col space-y-6">
      <JobConfigurationForm />
    </div>

    <!-- Right Column: Results & Logs -->
    <div class="lg:col-span-8 flex flex-col space-y-6">
      <div class="flex-1 min-h-[400px]">
        <ResultsDataGrid />
      </div>
      <StatusConsole />
    </div>
  </div>
</main>

<style>
  :global(body) {
    overflow-x: hidden;
  }
</style>
