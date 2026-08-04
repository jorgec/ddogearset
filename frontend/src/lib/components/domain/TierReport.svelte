<script lang="ts">
  // Post-solve trace of the sequential lexicographic solve
  // (docs/TIERED_SOLVER_FRONTEND_SPEC.md §7.2).
  //
  // This replaces the FUNCTION of the deleted filigree-bias readout (explaining
  // what drove the result) without reimplementing its MECHANISM: everything
  // here is the solver's own factual answer, so the display cannot drift from
  // what the solver actually did.
  //
  // Field names/shapes come from ResultPayload / TierReport in app.go.

  import { resultStore, configStore } from '$lib/store';

  $: report = $resultStore?.tierReport;
  $: tierScores = $resultStore?.tierScores ?? {};
  $: unmetTier4 = $resultStore?.unmetTier4 ?? [];
  $: unmatched = $resultStore?.unmatchedPriorities ?? [];
  // Go mirrors tierReport.degraded onto the top level after unmarshaling, but
  // fall back to the nested value so this renders correctly either way.
  $: degraded = $resultStore?.degraded ?? report?.degraded ?? false;

  $: scoreTiers = Object.keys(tierScores).sort();

  function fmt(n: number | undefined | null, digits = 2): string {
      return typeof n === 'number' ? n.toFixed(digits) : '—';
  }

  const STATUS_LABEL: Record<string, string> = {
      optimal: 'Optimal',
      time_limited: 'Time-limited',
      no_incumbent: 'No solution found',
      infeasible: 'Infeasible',
      lock_violation: 'Lock violation',
      unknown: 'Unknown',
      restored: 'Rolled back',
      failed: 'Failed',
  };
</script>

<!-- EC-10: absent data renders nothing at all, not an empty placeholder panel. -->
{#if report}
  <div class="rounded-lg border border-border bg-card/20 p-4 space-y-4">
    <div class="flex items-baseline justify-between gap-2">
      <h3 class="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
        Tier Solve Report
      </h3>
      <span class="text-xs text-muted-foreground">
        Last run: {fmt(report.totalElapsedSeconds, 1)}s of {$configStore.max_search_time}s budget
      </span>
    </div>

    {#if degraded}
      <div class="rounded-md border border-destructive/50 bg-destructive/10 p-3 space-y-1">
        <p class="text-xs font-semibold text-destructive">
          The solve completed but had to fall back somewhere. The result is still usable.
        </p>
        <!-- Notes are rendered verbatim: the solver writes human-readable
             explanations for exactly this situation, and re-wording them here
             would risk contradicting what actually happened. -->
        {#each report.notes ?? [] as note}
          <p class="text-[11px] text-destructive/90">{note}</p>
        {/each}
      </div>
    {/if}

    {#if report.stages && report.stages.length > 0}
      <div class="space-y-1">
        <p class="text-xs font-medium">Stages</p>
        <div class="overflow-x-auto">
          <table class="w-full text-[11px]">
            <thead class="text-muted-foreground">
              <tr class="text-left">
                <th class="py-1 pr-3 font-medium">Tier</th>
                <th class="py-1 pr-3 font-medium">Goal</th>
                <th class="py-1 pr-3 font-medium">Status</th>
                <th class="py-1 pr-3 font-medium">Time</th>
                <th class="py-1 font-medium">Folded in</th>
              </tr>
            </thead>
            <tbody>
              {#each report.stages as stage (stage.tier)}
                <tr class="border-t border-border/50">
                  <td class="py-1 pr-3">{stage.tier}</td>
                  <td class="py-1 pr-3">{fmt(stage.goalValue, 4)}</td>
                  <td class="py-1 pr-3">
                    <span class="{stage.proven ? 'text-green-500' : 'text-amber-500'}">
                      {stage.proven ? 'Optimal' : (STATUS_LABEL[stage.status] ?? stage.status)}
                    </span>
                  </td>
                  <td class="py-1 pr-3 text-muted-foreground">
                    {fmt(stage.elapsedSeconds, 1)}s / {fmt(stage.budgetSeconds, 1)}s
                  </td>
                  <td class="py-1 text-muted-foreground">
                    {stage.folded && stage.folded.length > 0 ? stage.folded.join(', ') : '—'}
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
        {#if report.stages.some((s) => !s.proven)}
          <p class="text-[10px] text-amber-500">
            At least one stage hit its time limit before proving optimality — raising Total Search
            Time may improve this result.
          </p>
        {/if}
      </div>
    {/if}

    {#if scoreTiers.length > 0}
      <div class="space-y-1">
        <p class="text-xs font-medium">Final tier scores</p>
        <div class="flex flex-wrap gap-2">
          {#each scoreTiers as t}
            <span class="rounded border border-border px-2 py-0.5 text-[11px]">
              Tier {t}: <span class="font-medium">{fmt(tierScores[t], 4)}</span>
            </span>
          {/each}
        </div>
        <p class="text-[10px] text-muted-foreground">
          Recomputed from the final reconciled solution, not echoed from the stage records.
        </p>
      </div>
    {/if}

    {#if report.consolidation || report.reconciliation}
      <div class="flex flex-wrap gap-4 text-[11px] text-muted-foreground">
        {#if report.consolidation}
          <span>
            Consolidation: {STATUS_LABEL[report.consolidation.status] ?? report.consolidation.status}
            · {report.consolidation.itemsEquipped} items
            · {report.consolidation.duplicateSources} duplicate sources
            · {fmt(report.consolidation.elapsedSeconds, 1)}s
          </span>
        {/if}
        {#if report.reconciliation}
          <span>
            Reconciliation: {STATUS_LABEL[report.reconciliation.status] ?? report.reconciliation.status}
            · {fmt(report.reconciliation.elapsedSeconds, 1)}s
          </span>
        {/if}
      </div>
    {/if}

    {#if unmetTier4.length > 0}
      <p class="text-[11px] text-muted-foreground">
        <span class="font-medium text-foreground">Tier 4 stats not reached</span>
        (would have cost a higher tier): {unmetTier4.join(', ')}.
      </p>
    {/if}

    {#if unmatched.length > 0}
      <p class="text-[11px] text-amber-500">
        <span class="font-medium">These priorities matched nothing in the data files:</span>
        {unmatched.join(', ')}. Check the spelling on the Solver tab — these chips are badged there.
      </p>
    {/if}
  </div>
{/if}
