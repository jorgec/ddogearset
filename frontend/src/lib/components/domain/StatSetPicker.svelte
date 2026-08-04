<script lang="ts">
  // Curated stat-set presets (docs/TIERED_SOLVER_FRONTEND_SPEC.md §6).
  //
  // Conflict resolution is additive-by-default: the user's own placement always
  // wins, with a single-step Undo and a one-click "Replace instead" rather than
  // a confirmation modal. Silently overwriting would destroy hand-tuning, and
  // under the tiered model moving a stat between tiers changes a hard
  // lexicographic lock — a much bigger invisible consequence per click than it
  // was under the old flat-weight system.

  import { onMount } from 'svelte';
  import { configStore, showToast, statSetUndoSnapshot, flashStats } from '$lib/store';
  import { loadStatSets } from '$lib/data/statSets';
  import type { StatSet, StatSetsFile } from '$lib/data/statSets';
  import {
      canAddStat,
      cloneLanes,
      findTier,
      hydrateLanes,
      serializePriorities,
  } from '$lib/data/statPriorities';
  import type { Tier } from '$lib/data/statPriorities';

  let sets: StatSet[] = [];
  let loading = true;
  let loadError = '';

  async function load(forceRefresh = false) {
      loading = true;
      loadError = '';
      try {
          const file: StatSetsFile = await loadStatSets(forceRefresh);
          sets = file?.sets ?? [];
      } catch (e) {
          loadError = String(e);
          sets = [];
      } finally {
          loading = false;
      }
  }

  onMount(() => load());

  // buildTypes is SOFT ordering only (§6.1/EC-4): matching sets float to the
  // top, but every set stays reachable so a mixed build or plain curiosity is
  // never blocked.
  $: orderedSets = [...sets].sort((a, b) => {
      const aMatch = a.buildTypes?.includes($configStore.build_type) ? 0 : 1;
      const bMatch = b.buildTypes?.includes($configStore.build_type) ? 0 : 1;
      return aMatch - bMatch;
  });

  function applySet(set: StatSet, replaceConflicts = false, snapshotOverride?: typeof $configStore.stat_priorities) {
      const base = snapshotOverride ?? $configStore.stat_priorities;
      const snapshot = (base ?? []).map((e) => ({ ...e }));
      const lanes = cloneLanes(hydrateLanes(base));

      let added = 0;
      let kept = 0;
      let blocked = 0;
      const conflicts: string[] = [];

      for (const p of set.priorities ?? []) {
          const stat = (p.stat ?? '').trim();
          if (!stat) continue;
          const tier = (p.tier >= 1 && p.tier <= 5 ? p.tier : 1) as Tier;
          const existing = findTier(lanes, stat);

          if (existing === null) {
              // Same gate as the picker and the legacy migration — a set must
              // not be able to sneak past the weapon-damage exclusion (§3.5).
              if (!canAddStat(lanes, stat).ok) {
                  blocked++;
                  continue;
              }
              lanes[tier].push({ stat, ...(p.cap ? { cap: p.cap } : {}) });
              added++;
              continue;
          }

          if (existing === tier) {
              kept++; // exact match: leave position and cap untouched
              continue;
          }

          conflicts.push(stat);
          if (replaceConflicts) {
              const idx = lanes[existing].findIndex(
                  (c) => c.stat.trim().toLowerCase() === stat.toLowerCase()
              );
              const [chip] = lanes[existing].splice(idx, 1);
              lanes[tier].push(chip);
          } else {
              kept++; // user placement wins
          }
      }

      $configStore.stat_priorities = serializePriorities(lanes);
      $statSetUndoSnapshot = snapshot;
      flashStats(conflicts);

      if (replaceConflicts) {
          showToast(
              `${set.name} re-applied — ${conflicts.length} stat(s) moved to the set's tiers.`,
              'success'
          );
          return;
      }

      const blockedText = blocked > 0 ? ` ${blocked} skipped (weapon damage conflict).` : '';
      showToast(
          `${set.name} applied — ${added} added, ${kept} already in your list (kept at your tiers).${blockedText}`,
          'success',
          [
              {
                  label: 'Undo',
                  onClick: () => {
                      // Snapshot is single-use (EC-7): consumed here, and the
                      // toast dismisses itself so the option can't be clicked
                      // a second time against stale state.
                      $configStore.stat_priorities = snapshot;
                      $statSetUndoSnapshot = null;
                  },
              },
              {
                  label: 'Replace instead',
                  onClick: () => applySet(set, true, snapshot),
              },
          ]
      );
  }
</script>

<div class="space-y-3">
  <div class="flex items-center justify-between">
    <p class="text-xs text-muted-foreground">
      Click a set to add its stats. Anything already in your list stays exactly where you put it.
    </p>
    <button
      type="button"
      class="rounded border border-border px-2 py-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
      on:click={() => load(true)}
      title="Re-read stat_sets.json from disk"
    >⟳ Reload</button>
  </div>

  {#if loading}
    <p class="text-xs text-muted-foreground">Loading stat sets…</p>
  {:else if loadError}
    <p class="text-xs text-destructive">Could not load stat sets: {loadError}</p>
  {:else if orderedSets.length === 0}
    <p class="text-xs text-muted-foreground">No stat sets defined.</p>
  {:else}
    <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
      {#each orderedSets as set (set.id)}
        <button
          type="button"
          class="text-left rounded-md border border-border bg-card p-3 hover:border-primary transition-colors"
          on:click={() => applySet(set)}
        >
          <div class="flex items-center justify-between gap-2">
            <span class="text-sm font-medium">{set.name}</span>
            {#if set.buildTypes?.includes($configStore.build_type)}
              <span class="text-[9px] uppercase text-primary shrink-0">Your build</span>
            {/if}
          </div>
          <p class="text-[11px] text-muted-foreground mt-1">{set.description}</p>
          {#if set.notes}
            <p class="text-[10px] text-muted-foreground italic mt-1">{set.notes}</p>
          {/if}
          <p class="text-[10px] text-muted-foreground mt-1">{set.priorities?.length ?? 0} stats</p>
        </button>
      {/each}
    </div>
  {/if}

  <p class="text-[10px] text-muted-foreground">
    Sets are read from <code>stat_sets.json</code> next to the app if present, otherwise from the
    bundled defaults. Edit that file by hand and press Reload.
  </p>
</div>
