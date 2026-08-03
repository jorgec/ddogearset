<script lang="ts">
  import { toastStore } from '$lib/store';
  import { fly } from 'svelte/transition';

  const kindClasses: Record<string, string> = {
      success: 'bg-green-600 text-white',
      error: 'bg-destructive text-destructive-foreground',
      info: 'bg-slate-800 text-white',
  };
</script>

<div class="fixed bottom-4 right-4 z-50 flex flex-col space-y-2 pointer-events-none">
  {#each $toastStore as toast (toast.id)}
      <div
          transition:fly={{ y: 16, duration: 200 }}
          class="pointer-events-auto rounded-md shadow-lg px-4 py-3 text-sm font-medium min-w-[220px] max-w-sm {kindClasses[toast.kind]}"
      >
          {toast.text}
      </div>
  {/each}
</div>
