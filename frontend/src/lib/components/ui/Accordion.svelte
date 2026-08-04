<script lang="ts">
  // Generic collapsible section.
  //
  // Hand-rolled on purpose (docs/TIERED_SOLVER_FRONTEND_SPEC.md §8.1): this
  // project is pinned to Svelte 3, and shadcn-svelte's Accordion wraps bits-ui,
  // which targets Svelte 4/5. Adopting it would mean either a Svelte major
  // upgrade or an old pinned release, plus four new runtime dependencies, for
  // one collapsible. This generalizes the toggle pattern the form already used
  // for Excluded Expansion Packs and keeps the same visual language.
  //
  // There is deliberately no AccordionGroup / mutual-exclusion wrapper —
  // sections open and close independently.

  export let title: string;
  export let open: boolean = false;
  /** Collapsed-state digest, e.g. "Reserved: Ring · 4 filigree slots". */
  export let summary: string | undefined = undefined;
  /**
   * localStorage key for open/closed persistence. Omit for sections that must
   * always mount in their declared state regardless of prior sessions (Stat
   * Priorities, per §8.3).
   */
  export let persistKey: string | undefined = undefined;

  let uid = Math.random().toString(36).slice(2, 9);
  $: contentId = `accordion-content-${uid}`;

  const storageKey = persistKey ? `accordion:${persistKey}` : undefined;

  // Read persisted state once, at init. Guarded because localStorage can throw
  // in private-browsing/WebView contexts, and a failed read must never keep the
  // section from rendering.
  if (storageKey) {
      try {
          const stored = localStorage.getItem(storageKey);
          if (stored === 'open') open = true;
          else if (stored === 'closed') open = false;
      } catch (e) {
          /* persistence is best-effort */
      }
  }

  function toggle() {
      open = !open;
      if (storageKey) {
          try {
              localStorage.setItem(storageKey, open ? 'open' : 'closed');
          } catch (e) {
              /* persistence is best-effort */
          }
      }
  }
</script>

<div class="space-y-2 border-t border-border pt-4">
  <button
    type="button"
    class="flex items-center justify-between w-full text-left"
    on:click={toggle}
    aria-expanded={open}
    aria-controls={contentId}
  >
    <span class="text-sm font-medium leading-none">{title}</span>
    <span class="flex items-center space-x-2">
      {#if !open && summary}
        <span class="text-muted-foreground text-xs">{summary}</span>
      {/if}
      <span class="text-muted-foreground">{open ? '▲' : '▼'}</span>
    </span>
  </button>
  {#if open}
    <div id={contentId} class="mt-2">
      <slot />
    </div>
  {/if}
</div>
