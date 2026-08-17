<script lang="ts">
  // Per-slot "find alternatives" drawer — docs/SLOT_ALTERNATIVES_UI_SPEC.md.
  //
  // Wires a previously-unused-from-the-frontend backend RPC (GetSlotAlternatives)
  // into the Gearset Editor. The RPC is enumeration-based, not an ILP solve — it
  // locks every other slot to the current gearset and scores each legal candidate
  // for `targetSlot` directly — so there is no search-time budget to configure here
  // (max_search_time travels on the payload but is never read on this code path).
  // The Trove owned-items restriction is already applied automatically: spreading
  // $configStore carries owned_item_names into the request, same as every other
  // RunOptimization call in this app.
  import { configStore, resultStore, showToast } from '$lib/store';
  import { GetSlotAlternatives } from '../../../../wailsjs/go/main/App';
  import type { main } from '../../../../wailsjs/go/models';
  import { fly, fade } from 'svelte/transition';

  // Named targetSlot, NOT slot — "slot" is a reserved Svelte attribute for
  // named-slot content projection, and a prop called `slot` silently never
  // receives its value when passed as `slot={...}` from a parent (Svelte's
  // compiler treats it as its own slot-name attribute instead of a prop).
  export let targetSlot: string;
  export let onClose: () => void;

  let loading = true;
  let error = '';
  let warnings: string[] = [];
  let alternatives: main.AlternativeItem[] = [];
  // Confirm-before-equip (docs/SLOT_ALTERNATIVES_UI_SPEC.md decision 4) — a
  // bigger, less deliberate action than the existing no-confirm item-search
  // selectItem() flow, so a row click only stages a candidate; a second,
  // explicit click actually equips it.
  let pendingEquip: main.AlternativeItem | null = null;

  async function load() {
      loading = true;
      error = '';
      warnings = [];
      alternatives = [];
      pendingEquip = null;
      try {
          const result = await GetSlotAlternatives({
              ...$configStore,
              target_slot: targetSlot,
              current_item: $resultStore?.gearSet?.[targetSlot] ?? '',
              equipped_items: $resultStore?.gearSet ?? {},
              // Always request the backend's own max (it clamps to [3,10]
              // regardless) — no count picker, per the confirmed spec.
              count: 10,
              mode: 'alternatives',
          } as unknown as main.AlternativesPayload);
          if (!result.success) {
              error = result.errorMessage || 'Failed to fetch alternatives.';
              return;
          }
          alternatives = result.alternatives ?? [];
          warnings = result.warnings ?? [];
      } catch (e) {
          error = 'Failed to fetch alternatives: ' + e;
      } finally {
          loading = false;
      }
  }

  // Re-fetch whenever the target slot changes (the parent reassigns
  // `targetSlot` rather than remounting this component between slots).
  $: if (targetSlot) load();

  function selectForEquip(alt: main.AlternativeItem) {
      pendingEquip = alt;
  }

  function cancelEquip() {
      pendingEquip = null;
  }

  function confirmEquip() {
      if (!pendingEquip) return;
      const alt = pendingEquip;

      // Snapshot the pre-swap state for a one-click "Restore" — filigrees are
      // gearset-wide (weapon/artifact buckets), not per-slot, so both buckets
      // are snapshotted regardless of which one this slot actually uses.
      const previousItem = $resultStore.gearSet?.[targetSlot];
      const previousAugments = $configStore.pre_filled_augments?.[targetSlot]
          ? { ...($configStore.pre_filled_augments[targetSlot] as Record<string, string>) }
          : undefined;
      const previousFiligreesWeapon = [...($configStore.pre_filled_filigrees?.weapon ?? [])];
      const previousFiligreesArtifact = [...($configStore.pre_filled_filigrees?.artifact ?? [])];

      // Equip — same base pattern as GearsetEditor's selectItem(), plus
      // applying the candidate's own precomputed augments/filigrees
      // (decision 3: apply them, don't leave those slots for the user to
      // redo by hand).
      $resultStore.gearSet[targetSlot] = alt.itemName;
      $configStore.pre_equipped[targetSlot] = alt.itemName;

      const augMap: Record<string, string> = {};
      for (const a of alt.augments ?? []) augMap[a.color] = a.name;
      if (Object.keys(augMap).length > 0) {
          $configStore.pre_filled_augments[targetSlot] = augMap;
      } else {
          delete $configStore.pre_filled_augments[targetSlot];
      }
      if (alt.filigrees?.weapon?.length) {
          $configStore.pre_filled_filigrees.weapon = alt.filigrees.weapon;
      }
      if (alt.filigrees?.artifact?.length) {
          $configStore.pre_filled_filigrees.artifact = alt.filigrees.artifact;
      }

      $resultStore.gearSet = { ...$resultStore.gearSet };
      $configStore.pre_equipped = { ...$configStore.pre_equipped };
      $configStore.pre_filled_augments = { ...$configStore.pre_filled_augments };
      $configStore.pre_filled_filigrees = { ...$configStore.pre_filled_filigrees };

      pendingEquip = null;

      showToast(`Equipped ${alt.itemName} in ${targetSlot}.`, 'success', [
          {
              label: 'Restore',
              onClick: () => {
                  if (previousItem) {
                      $resultStore.gearSet[targetSlot] = previousItem;
                      $configStore.pre_equipped[targetSlot] = previousItem;
                  } else {
                      delete $resultStore.gearSet[targetSlot];
                      delete $configStore.pre_equipped[targetSlot];
                  }
                  if (previousAugments) {
                      $configStore.pre_filled_augments[targetSlot] = previousAugments;
                  } else {
                      delete $configStore.pre_filled_augments[targetSlot];
                  }
                  $configStore.pre_filled_filigrees.weapon = previousFiligreesWeapon;
                  $configStore.pre_filled_filigrees.artifact = previousFiligreesArtifact;

                  $resultStore.gearSet = { ...$resultStore.gearSet };
                  $configStore.pre_equipped = { ...$configStore.pre_equipped };
                  $configStore.pre_filled_augments = { ...$configStore.pre_filled_augments };
                  $configStore.pre_filled_filigrees = { ...$configStore.pre_filled_filigrees };
              },
          },
      ]);

      onClose();
  }

  function formatDelta(v: number): string {
      const rounded = Math.round(v * 100) / 100;
      return (rounded > 0 ? '+' : '') + rounded;
  }

  // Phase 11 §5.3 limit indicators — warn when equipping an alternative would
  // violate a global limit, without hiding the item from the list entirely.
  $: minorArtifactElsewhere = Object.entries($resultStore?.slots ?? {}).some(
      ([slot, detail]) => slot !== targetSlot && detail?.item?.minor
  );
  $: raidCountElsewhere = Object.entries($resultStore?.slots ?? {}).filter(
      ([slot, detail]) => slot !== targetSlot && detail?.item?.is_raid
  ).length;
  $: raidLimitReached = raidCountElsewhere >= ($configStore.raid_item_limit ?? 2);

  function limitBorderClass(alt: main.AlternativeItem): string {
      if (alt.isMinor && minorArtifactElsewhere) return 'ring-2 ring-blood';
      if (alt.isRaid && raidLimitReached) return 'ring-2 ring-gold';
      return '';
  }

  function limitTooltip(alt: main.AlternativeItem): string {
      if (alt.isMinor && minorArtifactElsewhere) return 'A Minor Artifact is already equipped in another slot';
      if (alt.isRaid && raidLimitReached) return `Raid item limit (${$configStore.raid_item_limit ?? 2}) already reached from other slots`;
      return '';
  }
</script>

<button
  class="fixed inset-0 z-40 bg-void/70 backdrop-blur-md"
  on:click={onClose}
  aria-label="Close alternatives"
  transition:fade={{ duration: 150 }}
></button>
<div
  class="fixed top-0 right-0 z-50 h-full w-full max-w-xl bg-background border-l border-border shadow-2xl overflow-y-auto flex flex-col"
  transition:fly={{ x: 400, duration: 200 }}
>
  <div class="sticky top-0 z-10 flex items-center justify-between px-6 py-4 bg-background/95 backdrop-blur border-b border-border">
    <div>
      <h3 class="font-semibold text-lg">Alternatives — {targetSlot.replace('_1', ' 1').replace('_2', ' 2')}</h3>
      {#if $resultStore?.gearSet?.[targetSlot]}
        <p class="text-xs text-muted-foreground">Currently: {$resultStore.gearSet[targetSlot]}</p>
      {:else}
        <p class="text-xs text-muted-foreground italic">Currently empty</p>
      {/if}
    </div>
    <button type="button" on:click={onClose} class="text-muted-foreground hover:text-foreground p-1 shrink-0" aria-label="Close">
      <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
    </button>
  </div>

  <div class="flex-1 p-6 space-y-3">
    {#if loading}
      <p class="text-muted-foreground animate-pulse">Finding alternatives…</p>
    {:else if error}
      <p class="text-destructive text-sm">{error}</p>
    {:else}
      {#each warnings as w}
        <p class="text-sm text-gold italic">{w}</p>
      {/each}
      {#if alternatives.length === 0}
        <p class="text-muted-foreground text-sm italic">No alternatives found for this slot.</p>
      {:else}
      {#each alternatives as alt (alt.rank)}
        <div class="rounded-md border {pendingEquip === alt ? 'border-primary' : 'border-border'} {limitBorderClass(alt)} bg-card/40 p-3 space-y-2"
             title={limitTooltip(alt)}>
          <button type="button" class="w-full text-left" on:click={() => selectForEquip(alt)}>
            <div class="flex items-center justify-between gap-2">
              <span class="font-medium">#{alt.rank} {alt.itemName}</span>
              <span class="text-xs text-muted-foreground shrink-0">
                ML {alt.ml}{alt.isRaid ? ' · Raid' : ''}{alt.isMinor ? ' · Minor Artifact' : ''}
              </span>
            </div>
            {#if alt.statDeltas && Object.keys(alt.statDeltas).length > 0}
              <div class="flex flex-wrap gap-x-3 gap-y-1 mt-1">
                {#each Object.entries(alt.statDeltas) as [stat, delta]}
                  <span class="text-xs {delta > 0 ? 'text-primary' : delta < 0 ? 'text-destructive' : 'text-muted-foreground'}">
                    {stat}: {formatDelta(delta)}
                  </span>
                {/each}
              </div>
            {/if}
          </button>

          {#if pendingEquip === alt}
            <div class="flex items-center justify-between gap-2 pt-2 border-t border-border/50">
              <span class="text-xs text-muted-foreground">Equip {alt.itemName}?</span>
              <div class="flex gap-2">
                <button type="button" on:click={cancelEquip} class="px-2 py-1 text-xs rounded bg-muted text-muted-foreground hover:bg-muted/80 transition-colors">Cancel</button>
                <button type="button" on:click={confirmEquip} class="px-2 py-1 text-xs rounded bg-primary text-primary-foreground hover:bg-primary/90 transition-colors">Confirm</button>
              </div>
            </div>
          {/if}
        </div>
      {/each}
      {/if}
    {/if}
  </div>
</div>
