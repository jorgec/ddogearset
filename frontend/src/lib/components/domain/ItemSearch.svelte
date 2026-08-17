<script lang="ts">
  import { configStore, showToast } from '$lib/store';
  import { SearchItemsByStat } from '../../../../wailsjs/go/main/App';
  import StatPicker from './StatPicker.svelte';
  import Accordion from '../ui/Accordion.svelte';
  import { openWikiSearch, wikiSearchURL } from '$lib/wiki';

  let selectedStat: string | null = null;
  let showPicker = false;
  let isSearching = false;

  interface SearchEntry {
      sourceType: string;
      sourceName: string;
      bonusType: string;
      value: number;
      ml: number;
      slots?: string[];
      pack?: string;
  }

  let resultsByBonusType: Record<string, SearchEntry[]> = {};
  let totalResults = 0;

  async function performSearch(stat: string) {
      selectedStat = stat;
      showPicker = false;
      isSearching = true;
      resultsByBonusType = {};
      totalResults = 0;

      try {
          const res = await SearchItemsByStat(stat, $configStore.max_level);
          if (res && res.success) {
              const groups: Record<string, SearchEntry[]> = {};
              let count = 0;
              for (const entry of (res.results || [])) {
                  if (!groups[entry.bonusType]) {
                      groups[entry.bonusType] = [];
                  }
                  groups[entry.bonusType].push(entry);
                  count++;
              }
              // Sort by value descending within each group
              for (const key in groups) {
                  groups[key].sort((a, b) => b.value - a.value);
              }
              resultsByBonusType = groups;
              totalResults = count;
          } else {
              showToast(res?.errorMessage || 'Search failed.', 'error');
          }
      } catch (e) {
          console.error(e);
          showToast('Search failed: ' + e, 'error');
      } finally {
          isSearching = false;
      }
  }
</script>

<div class="panel flex flex-col h-full space-y-3 p-3">
  <div class="flex items-center justify-between gap-2">
    <div>
      <h2 class="panel-title text-sm">Item Search by Stat</h2>
      <p class="text-[11px] text-steel mt-1">Browse items, augments, and filigrees granting a specific stat.</p>
    </div>
  </div>

  <div class="flex flex-col space-y-4">
    <div class="relative">
      <button 
          on:click={() => showPicker = !showPicker}
          class="px-4 py-2 bg-secondary text-secondary-foreground border border-border rounded shadow-sm flex items-center space-x-2 hover:bg-secondary/80 transition-colors"
      >
          <span>{selectedStat ? `Searching: ${selectedStat}` : 'Select a Stat...'}</span>
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>
      </button>

      {#if showPicker}
          <StatPicker
              buildType={$configStore.build_type}
              on:select={(e) => performSearch(e.detail)}
              on:close={() => showPicker = false}
          />
      {/if}
    </div>

    {#if isSearching}
      <div class="py-12 flex justify-center">
          <span class="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent"></span>
      </div>
    {:else if selectedStat}
      <div class="text-sm text-muted-foreground italic mb-2">
          Found {totalResults} matches for "{selectedStat}" (ML {Math.max(1, $configStore.max_level - 6)} – {$configStore.max_level}).
      </div>

      <div class="space-y-1">
          {#each Object.entries(resultsByBonusType).sort(([a], [b]) => a.localeCompare(b)) as [bonusType, entries]}
              <Accordion title="{bonusType} ({entries.length})">
                  <div class="overflow-x-auto px-1 pb-2">
                      <table class="w-full text-sm text-left">
                          <thead class="text-xs text-muted-foreground uppercase bg-muted/50 border-b border-border">
                              <tr>
                                  <th class="px-3 py-2 font-medium">Value</th>
                                  <th class="px-3 py-2 font-medium">Source</th>
                                  <th class="px-3 py-2 font-medium">Type</th>
                                  <th class="px-3 py-2 font-medium">Details</th>
                              </tr>
                          </thead>
                          <tbody class="divide-y divide-border">
                              {#each entries as entry}
                                  <tr class="hover:bg-muted/30 transition-colors">
                                      <td class="px-3 py-2 font-semibold text-primary">{entry.value}</td>
                                      <td class="px-3 py-2 font-medium">
                                          <!--
                                            A button, not an <a href>. An anchor
                                            navigates the WEBVIEW to ddowiki and the
                                            app is simply gone — no error, no way
                                            back. BrowserOpenURL hands it to the real
                                            browser instead. Guarded by
                                            TestFrontendOpensExternalLinksThroughWails.
                                          -->
                                          <button
                                              type="button"
                                              on:click={() => openWikiSearch(entry.sourceName)}
                                              title="Look up “{entry.sourceName}” on ddowiki — {wikiSearchURL(entry.sourceName)}"
                                              class="text-left text-foreground underline decoration-dotted decoration-primary/40 underline-offset-2 hover:text-primary hover:decoration-primary transition-colors"
                                          >{entry.sourceName}</button>
                                      </td>
                                      <td class="px-3 py-2 text-muted-foreground capitalize">{entry.sourceType}</td>
                                      <td class="px-3 py-2 text-xs text-muted-foreground">
                                          <div class="flex flex-col space-y-0.5">
                                              <span>ML {entry.ml}</span>
                                              {#if entry.slots && entry.slots.length > 0}
                                                  <span>Slots: {entry.slots.join(', ')}</span>
                                              {/if}
                                              {#if entry.pack}
                                                  <span class="italic text-primary/70">{entry.pack}</span>
                                              {/if}
                                          </div>
                                      </td>
                                  </tr>
                              {/each}
                          </tbody>
                      </table>
                  </div>
              </Accordion>
          {/each}
      </div>
    {/if}
  </div>
</div>
