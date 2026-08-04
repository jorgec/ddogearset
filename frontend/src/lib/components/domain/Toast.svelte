<script lang="ts">
  import { toastStore, dismissToast } from '$lib/store';
  import type { ToastAction } from '$lib/store';
  import { fly } from 'svelte/transition';

  const kindClasses: Record<string, string> = {
      success: 'bg-green-600 text-white',
      error: 'bg-destructive text-destructive-foreground',
      info: 'bg-slate-800 text-white',
  };

  // An action consumes the toast: the caller's snapshot-based Undo is
  // single-use (spec EC-7), so leaving the buttons on screen after a click
  // would offer an option that no longer does anything.
  function runAction(id: number, action: ToastAction) {
      action.onClick();
      dismissToast(id);
  }
</script>

<div class="fixed bottom-4 right-4 z-50 flex flex-col space-y-2 pointer-events-none">
  {#each $toastStore as toast (toast.id)}
      <div
          transition:fly={{ y: 16, duration: 200 }}
          class="pointer-events-auto rounded-md shadow-lg px-4 py-3 text-sm font-medium min-w-[220px] max-w-sm {kindClasses[toast.kind]}"
      >
          <div>{toast.text}</div>
          {#if toast.actions && toast.actions.length > 0}
              <div class="mt-2 flex gap-2">
                  {#each toast.actions as action}
                      <button
                          class="rounded border border-white/40 px-2 py-1 text-xs font-semibold hover:bg-white/20 transition-colors"
                          on:click={() => runAction(toast.id, action)}
                      >{action.label}</button>
                  {/each}
              </div>
          {/if}
      </div>
  {/each}
</div>
