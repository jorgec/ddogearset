<script lang="ts">
  // docs/DASHBOARD_REDESIGN_SPEC.md — the single-page dashboard that replaces
  // the old six-tab layout. Zone widths (25% / 45% / 30%) come straight from
  // the design spec's §5 table.
  import { onMount } from 'svelte';
  import JobConfigurationForm from '$lib/components/domain/JobConfigurationForm.svelte';
  import GearsetEditor from '$lib/components/domain/GearsetEditor.svelte';
  import Summary from '$lib/components/domain/Summary.svelte';
  import HarnessBoard from '$lib/components/domain/HarnessBoard.svelte';
  import GearChecklist from '$lib/components/domain/GearChecklist.svelte';
  import ItemSearch from '$lib/components/domain/ItemSearch.svelte';
  import OwnedItems from '$lib/components/domain/OwnedItems.svelte';
  import StatusConsole from '$lib/components/domain/StatusConsole.svelte';
  import Toast from '$lib/components/domain/Toast.svelte';
  import { ParseMetadata } from '../wailsjs/go/main/App';
  import { isParsing, isOptimizing, rightPanel, drawerOpen, type RightPanel } from '$lib/store';
  import logoUrl from './assets/images/logo.jpg';

  // §4.1 "The Belt" — icons accompany the text on every stud.
  const RIGHT_PANELS: { id: RightPanel; label: string; icon: string }[] = [
    // terminal
    { id: 'console', label: 'Console', icon: 'M4 17l6-6-6-6M12 19h8' },
    // archive / chest
    { id: 'ownedItems', label: 'Owned Items', icon: 'M3 8h18v11a1 1 0 01-1 1H4a1 1 0 01-1-1V8zM2 4h20v4H2zM10 12h4' },
    // magnifier
    { id: 'itemSearch', label: 'Search', icon: 'M11 19a8 8 0 100-16 8 8 0 000 16zM21 21l-4.35-4.35' },
  ];

  onMount(async () => {
    $isParsing = true;
    try {
      await ParseMetadata('data/metadata.xml');
    } catch (e) {
      console.error(e);
    } finally {
      $isParsing = false;
    }
  });

  $: busy = $isParsing || $isOptimizing;

  // Centre-column view toggle: summary (the Vellum Scroll), harness board, or gear checklist.
  let centreView: 'summary' | 'harness' | 'checklist' = 'summary';

</script>

<main class="h-screen flex flex-col overflow-hidden">
  <!-- ==================== Title bar ==================== -->
  <header class="flex items-center justify-between px-5 py-2.5 bg-obsidian border-b border-carved shrink-0">
    <div class="flex items-center gap-3 min-w-0">
      <img src={logoUrl} alt="" class="h-9 w-9 rounded shadow-gold shrink-0" />
      <h1 class="panel-title text-lg md:text-xl truncate">DDO Gear Optimizer</h1>
      <!-- §4.1 — the "System Ready" dot is a glowing crystal. -->
      <span class="flex items-center gap-2 shrink-0 ml-2" title={busy ? 'Working…' : 'System ready'}>
        <span class="crystal {busy ? 'crystal-busy' : 'crystal-ready'}"></span>
        <span class="text-[11px] uppercase tracking-widest {busy ? 'text-gold' : 'text-vitality'} hidden sm:inline">
          {$isOptimizing ? 'Solving' : $isParsing ? 'Parsing' : 'Ready'}
        </span>
      </span>
    </div>

    <!-- ==================== The Belt ==================== -->
    <nav class="belt flex items-center gap-1 px-2 py-1 rounded-lg" aria-label="Readout panels">
      {#each RIGHT_PANELS as p}
        <button
          type="button"
          on:click={() => ($rightPanel = p.id)}
          aria-pressed={$rightPanel === p.id}
          class="belt-stud flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium
                 {$rightPanel === p.id ? 'belt-stud-active' : ''}"
        >
          <svg class="h-3.5 w-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d={p.icon} />
          </svg>
          <span class="hidden md:inline">{p.label}</span>
        </button>
      {/each}
    </nav>
  </header>

  <!-- ==================== Dashboard ==================== -->
  <!-- One grid owns the whole body, because the configuration drawer is no
       longer a full-width strip under everything: it occupies the columns
       1-2 region only, while the console column runs the FULL height beside
       it (row-span-2) and is unaffected by the drawer opening.

       Columns: 5fr / 9fr / 6fr == the design spec's 25% / 45% / 30%.
       Rows swap which band gets the free space:
         closed -> sockets+vellum take it, drawer is just its title bar
         open   -> the drawer takes it, sockets+vellum collapse to header
                   strips (still visible as context, per the mockup)
       Row placement is lg-only; below that everything stacks in DOM order. -->
  <div
    class="flex-1 min-h-0 grid grid-cols-1 gap-3 p-3 overflow-y-auto lg:overflow-hidden
           lg:grid-cols-[5fr_9fr_6fr]
           {$drawerOpen
             ? 'lg:grid-rows-[minmax(0,6.5rem)_minmax(0,1fr)]'
             : 'lg:grid-rows-[minmax(0,1fr)_auto]'}"
  >
    <!-- Left 25% — Gear Sockets (§4.2) -->
    <section class="min-h-0 lg:col-start-1 lg:row-start-1 lg:overflow-hidden" aria-label="Gear sockets">
      <GearsetEditor />
    </section>

    <!-- Center 45% — The Vellum Scroll / Harness Board -->
    <section class="min-h-0 lg:col-start-2 lg:row-start-1 lg:overflow-hidden flex flex-col" aria-label="Centre panel">
      <div class="flex items-center gap-1 px-2 pb-1 shrink-0">
        <button
          type="button"
          on:click={() => (centreView = 'summary')}
          class="belt-stud px-2.5 py-1 text-xs {centreView === 'summary' ? 'belt-stud-active' : ''}"
        >Summary</button>
        <button
          type="button"
          on:click={() => (centreView = 'harness')}
          class="belt-stud px-2.5 py-1 text-xs {centreView === 'harness' ? 'belt-stud-active' : ''}"
        >Harness</button>
        <button
          type="button"
          on:click={() => (centreView = 'checklist')}
          class="belt-stud px-2.5 py-1 text-xs {centreView === 'checklist' ? 'belt-stud-active' : ''}"
        >Checklist</button>
      </div>
      <div class:hidden={centreView !== 'summary'} class="flex-1 min-h-0 overflow-hidden">
        <Summary />
      </div>
      <div class:hidden={centreView !== 'harness'} class="flex-1 min-h-0 overflow-hidden">
        <HarnessBoard onSwitchToSummary={() => (centreView = 'summary')} />
      </div>
      <div class:hidden={centreView !== 'checklist'} class="flex-1 min-h-0 overflow-hidden">
        <GearChecklist />
      </div>
    </section>

    <!-- Right 30% — Console & Trove (§4.4). Spans both rows: full height in
         either drawer state. All three readouts stay mounted; only visibility
         toggles, so switching never drops scroll position, an in-flight
         search, or a loaded CSV. -->
    <section class="min-h-0 lg:col-start-3 lg:row-start-1 lg:row-span-2 lg:overflow-hidden" aria-label="Readouts">
      <div class:hidden={$rightPanel !== 'console'} class="h-full"><StatusConsole /></div>
      <div class:hidden={$rightPanel !== 'ownedItems'} class="h-full"><OwnedItems /></div>
      <div class:hidden={$rightPanel !== 'itemSearch'} class="h-full"><ItemSearch /></div>
    </section>

    <!-- Configuration & Auto-Solver (§5) — spans columns 1-2 only. -->
    <div class="min-h-0 lg:col-start-1 lg:col-span-2 lg:row-start-2 panel flex flex-col">
      <div class="flex items-center gap-1 px-3 shrink-0">
        <button
          type="button"
          on:click={() => ($drawerOpen = !$drawerOpen)}
          aria-expanded={$drawerOpen}
          class="flex items-center gap-2 py-2 pr-4 text-xs panel-title hover:text-vellum transition-colors"
        >
          <svg class="h-3 w-3 transition-transform duration-200 {$drawerOpen ? '' : '-rotate-90'}"
               viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M12 16L6 9h12z" />
          </svg>
          Configuration &amp; Auto-Solver
        </button>
      </div>

      {#if $drawerOpen}
        <div class="flex-1 min-h-0 overflow-y-auto border-t border-carved p-3">
          <JobConfigurationForm />
        </div>
      {/if}
    </div>
  </div>
</main>

<Toast />

<style>
  :global(body) {
    overflow-x: hidden;
  }
</style>
