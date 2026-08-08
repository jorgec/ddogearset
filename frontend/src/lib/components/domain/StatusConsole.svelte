<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { GetSystemLogs } from '../../../../wailsjs/go/main/App';
  import { logsStore } from '$lib/store';

  let consoleRef: HTMLDivElement;
  let intervalId: number;

  async function fetchLogs() {
    try {
      const logs = await GetSystemLogs();
      $logsStore = logs;
      
      // Auto-scroll to bottom
      if (consoleRef) {
        setTimeout(() => {
          consoleRef.scrollTop = consoleRef.scrollHeight;
        }, 10);
      }
    } catch (err) {
      console.error("Failed to fetch logs:", err);
    }
  }

  onMount(() => {
    fetchLogs();
    intervalId = setInterval(fetchLogs, 1000) as unknown as number;
  });

  onDestroy(() => {
    if (intervalId) clearInterval(intervalId);
  });
</script>

<!-- §4.4 — "styled like an arcane terminal": monospace, scanlines and a soft
     blue glow, all carried by the .arcane-console component class. -->
<div class="arcane-console flex flex-col h-full min-h-[16rem]">
  <div class="flex items-center gap-2 px-3 py-2 border-b border-arcane/25 text-[11px] uppercase tracking-widest text-arcane shrink-0">
    <span class="crystal crystal-ready !w-2 !h-2"></span>
    System Console
  </div>
  <div
    bind:this={consoleRef}
    class="flex-1 overflow-y-auto p-3 text-xs space-y-0.5 relative z-10"
  >
    {#if $logsStore.length === 0}
      <div class="text-steel/50 italic">Awaiting transmission…</div>
    {:else}
      {#each $logsStore as log}
        <div class="text-vellum/85 hover:bg-arcane/10 px-1.5 py-0.5 rounded transition-colors">
          <span class="text-arcane/70 mr-1.5 select-none">&gt;</span>{log}
        </div>
      {/each}
    {/if}
  </div>
</div>
