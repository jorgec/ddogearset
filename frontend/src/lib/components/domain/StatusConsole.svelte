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

<div class="glass-panel overflow-hidden flex flex-col h-64 border-slate-800 bg-slate-950/90 text-slate-50">
  <div class="flex items-center px-4 py-2 bg-slate-900 border-b border-slate-800 text-xs font-mono text-slate-400">
    <span class="flex h-2 w-2 rounded-full bg-green-500 mr-2"></span>
    System Console
  </div>
  <div 
    bind:this={consoleRef}
    class="flex-1 overflow-y-auto p-4 font-mono text-sm space-y-1"
  >
    {#if $logsStore.length === 0}
      <div class="text-slate-600 italic">No logs available...</div>
    {:else}
      {#each $logsStore as log}
        <div class="text-slate-300 hover:bg-slate-800/50 px-2 py-0.5 rounded">
          <span class="text-slate-500 mr-2">></span>
          {log}
        </div>
      {/each}
    {/if}
  </div>
</div>
