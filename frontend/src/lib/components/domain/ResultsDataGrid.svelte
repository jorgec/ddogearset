<script lang="ts">
  import { resultStore } from '$lib/store';
</script>

<div class="glass-panel p-6 space-y-6 h-full flex flex-col">
  <div class="space-y-2">
    <h2 class="text-xl font-semibold tracking-tight">Optimization Results</h2>
    <p class="text-sm text-muted-foreground">View the resulting optimal gear configuration and statistics.</p>
  </div>

  {#if $resultStore}
    <div class="grid gap-4 md:grid-cols-2">
      <div class="rounded-lg border bg-card text-card-foreground shadow-sm p-6">
        <h3 class="text-sm font-medium">Status</h3>
        <p class="text-2xl font-bold mt-2">
          {#if $resultStore.success}
            <span class="text-green-600 dark:text-green-500">Success</span>
          {:else}
            <span class="text-destructive">Failed</span>
          {/if}
        </p>
      </div>
      <div class="rounded-lg border bg-card text-card-foreground shadow-sm p-6">
        <h3 class="text-sm font-medium">Time Taken</h3>
        <p class="text-2xl font-bold mt-2">{$resultStore.timeTaken.toFixed(2)}s</p>
      </div>
    </div>

    {#if $resultStore.errorMessage}
      <div class="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-destructive">
        <p class="text-sm font-medium">{$resultStore.errorMessage}</p>
      </div>
    {/if}

    {#if $resultStore.gearSet && Object.keys($resultStore.gearSet).length > 0}
      <div class="rounded-md border flex-1 overflow-hidden flex flex-col">
        <div class="bg-muted/50 p-3 border-b sticky top-0 backdrop-blur-sm">
          <h4 class="text-sm font-semibold">Gear Configuration</h4>
        </div>
        <div class="overflow-y-auto p-0 flex-1 relative">
          <table class="w-full text-sm">
            <thead class="bg-muted/30">
              <tr>
                <th class="p-3 text-left font-medium text-muted-foreground w-1/3">Slot</th>
                <th class="p-3 text-left font-medium text-muted-foreground">Item</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border">
              {#each Object.entries($resultStore.gearSet) as [slot, item]}
                <tr class="transition-colors hover:bg-muted/50 data-[state=selected]:bg-muted">
                  <td class="p-3 font-medium border-r border-border/50">
                    {slot}
                  </td>
                  <td class="p-3 font-mono">
                    {item}
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </div>
    {/if}
  {:else}
    <div class="flex-1 flex items-center justify-center border-2 border-dashed rounded-lg p-12 text-center text-muted-foreground">
      <p>Configure and run an optimization job to view results here.</p>
    </div>
  {/if}
</div>
