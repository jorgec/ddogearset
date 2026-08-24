<script lang="ts">
  // Item Search — a catalog browser, deliberately independent of the
  // configuration panel.
  //
  // It used to read $configStore.max_level for its level window and
  // $configStore.build_type for the stat picker, which made "what exists in the
  // game" a question you could only ask about the build you happened to be
  // solving for: narrowing a build's level cap silently narrowed the browser
  // too, and there was no way to look two slots or ten levels away without
  // editing the build. Every bound of the search now lives here, and nothing
  // this panel does touches the build.
  import { showToast } from '$lib/store';
  import { SearchItems } from '../../../../wailsjs/go/main/App';
  import StatPicker from './StatPicker.svelte';
  import Accordion from '../ui/Accordion.svelte';
  import { openWikiSearch, wikiSearchURL } from '$lib/wiki';

  type Mode = 'stat' | 'name';

  // The catalog's own slot vocabulary (item_slot.slot), not the gearset's:
  // there is one "Ring", not Ring_1/Ring_2, because an item is not eligible
  // for a particular finger.
  const SLOTS = [
    'Helmet', 'Goggles', 'Necklace', 'Trinket', 'Cloak', 'Belt', 'Ring',
    'Gloves', 'Boots', 'Bracers', 'Armor', 'Weapon1', 'Weapon2',
  ];

  const LEVEL_FLOOR = 1;
  const LEVEL_CEILING = 40;

  let mode: Mode = 'stat';
  let selectedStat = '';
  let nameQuery = '';
  let minLevel = LEVEL_FLOOR;
  let maxLevel = 34;
  let slot = '';

  let showPicker = false;
  let isSearching = false;
  let hasSearched = false;

  interface SearchEntry {
      sourceType: string;
      sourceName: string;
      bonusType: string;
      value: number;
      ml: number;
      slots?: string[];
      pack?: string;
      stats?: string[];
      isRaid?: boolean;
  }

  let results: SearchEntry[] = [];
  let resultMode: Mode = 'stat';
  let searchedFor = '';

  $: query = mode === 'stat' ? selectedStat : nameQuery;

  // Stat results are one row per BUFF, so they group by bonus type — that
  // grouping is the whole point of the view (what is the best Insightful
  // Constitution item?). Name results are one row per SOURCE and have no bonus
  // type at all, so they stay a flat, level-sorted list.
  $: grouped = (() => {
      const groups: Record<string, SearchEntry[]> = {};
      if (resultMode !== 'stat') return groups;
      for (const entry of results) {
          (groups[entry.bonusType] ||= []).push(entry);
      }
      for (const key in groups) groups[key].sort((a, b) => b.value - a.value);
      return groups;
  })();

  // Every input re-runs the search, so a filter change never leaves rows on
  // screen that no longer match it. Debounced because a name search fires on
  // each keystroke and a stat search spawns the solver: `token` is what makes
  // an overtaken response drop its results instead of overwriting fresher ones.
  let timer: ReturnType<typeof setTimeout> | undefined;
  let token = 0;

  $: schedule(mode, query, minLevel, maxLevel, slot);

  function schedule(..._deps: unknown[]) {
      clearTimeout(timer);
      if (!query.trim()) {
          token++;
          results = [];
          hasSearched = false;
          isSearching = false;
          return;
      }
      timer = setTimeout(runSearch, mode === 'name' ? 250 : 500);
  }

  async function runSearch() {
      const mine = ++token;
      const requestedMode = mode;
      const requestedQuery = query.trim();
      isSearching = true;
      try {
          const res = await SearchItems(
              requestedMode, requestedQuery, clamp(minLevel), clamp(maxLevel), slot,
          );
          if (mine !== token) return;
          if (!res || !res.success) {
              results = [];
              showToast(res?.errorMessage || 'Search failed.', 'error');
              return;
          }
          results = (res.results || []) as SearchEntry[];
          resultMode = requestedMode;
          searchedFor = requestedQuery;
          hasSearched = true;
      } catch (e) {
          if (mine !== token) return;
          console.error(e);
          results = [];
          showToast('Search failed: ' + e, 'error');
      } finally {
          if (mine === token) isSearching = false;
      }
  }

  function clamp(level: number): number {
      if (!Number.isFinite(level)) return LEVEL_FLOOR;
      return Math.min(LEVEL_CEILING, Math.max(LEVEL_FLOOR, Math.round(level)));
  }

  function pickStat(stat: string) {
      selectedStat = stat;
      showPicker = false;
  }

  function setMode(next: Mode) {
      if (mode === next) return;
      mode = next;
      showPicker = false;
  }

  function slotsLabel(entry: SearchEntry): string {
      if (!entry.slots || entry.slots.length === 0) return '';
      // Augment rows carry their colours here rather than equipment slots —
      // that is what a "slot" means for an augment.
      return entry.slots.join(', ');
  }
</script>

<div class="panel flex flex-col h-full p-3 space-y-3 overflow-hidden">
  <div>
    <h2 class="panel-title text-sm">Item Search</h2>
    <p class="text-[11px] text-steel mt-1">
      Browse items, augments and filigrees by stat or by name. Independent of the
      build you are solving for — nothing here changes your configuration.
    </p>
  </div>

  <!-- mode -->
  <div class="flex items-center gap-1 shrink-0">
    <button
      type="button"
      on:click={() => setMode('stat')}
      class="px-3 py-1 text-[11px] rounded border transition-colors
             {mode === 'stat'
               ? 'bg-carved text-vellum border-carved'
               : 'text-steel border-transparent hover:text-vellum hover:bg-carved/50'}"
    >By stat</button>
    <button
      type="button"
      on:click={() => setMode('name')}
      class="px-3 py-1 text-[11px] rounded border transition-colors
             {mode === 'name'
               ? 'bg-carved text-vellum border-carved'
               : 'text-steel border-transparent hover:text-vellum hover:bg-carved/50'}"
    >By name</button>
  </div>

  <!-- query -->
  <div class="relative shrink-0">
    {#if mode === 'stat'}
      <button
        on:click={() => showPicker = !showPicker}
        class="w-full px-4 py-2 bg-secondary text-secondary-foreground border border-border rounded shadow-sm flex items-center justify-between gap-2 hover:bg-secondary/80 transition-colors"
      >
        <span class="truncate">{selectedStat ? `Searching: ${selectedStat}` : 'Select a Stat...'}</span>
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>
      </button>

      {#if showPicker}
        <!-- buildType is a soft sort inside the picker (nothing is ever
             hidden), so this panel passes its own neutral default rather than
             reaching into the build's configuration. -->
        <StatPicker
          buildType="Melee"
          on:select={(e) => pickStat(e.detail)}
          on:close={() => showPicker = false}
        />
      {/if}
    {:else}
      <input
        type="text"
        bind:value={nameQuery}
        placeholder="Item, augment or filigree name…"
        class="w-full h-9 rounded-md border border-input bg-void px-3 py-1 text-sm placeholder:text-steel/50 focus:outline-none focus:ring-1 focus:ring-gold/40"
      />
    {/if}
  </div>

  <!-- filters -->
  <div class="flex flex-wrap items-end gap-3 shrink-0">
    <label class="flex flex-col gap-1">
      <span class="text-[10px] uppercase tracking-wider text-steel/70">Min ML</span>
      <input
        type="number" min={LEVEL_FLOOR} max={LEVEL_CEILING}
        bind:value={minLevel}
        class="w-16 h-8 rounded-md border border-input bg-void px-2 text-sm focus:outline-none focus:ring-1 focus:ring-gold/40"
      />
    </label>
    <label class="flex flex-col gap-1">
      <span class="text-[10px] uppercase tracking-wider text-steel/70">Max ML</span>
      <input
        type="number" min={LEVEL_FLOOR} max={LEVEL_CEILING}
        bind:value={maxLevel}
        class="w-16 h-8 rounded-md border border-input bg-void px-2 text-sm focus:outline-none focus:ring-1 focus:ring-gold/40"
      />
    </label>
    <label class="flex flex-col gap-1 min-w-0">
      <span class="text-[10px] uppercase tracking-wider text-steel/70">Slot</span>
      <select
        bind:value={slot}
        class="h-8 rounded-md border border-input bg-void px-2 text-sm focus:outline-none focus:ring-1 focus:ring-gold/40"
      >
        <option value="">Any slot</option>
        {#each SLOTS as s}
          <option value={s}>{s.replace('Weapon1', 'Main hand').replace('Weapon2', 'Off hand')}</option>
        {/each}
      </select>
    </label>
    {#if slot}
      <p class="text-[10px] text-steel/60 pb-2">Augments and filigrees are hidden while a slot filter is set.</p>
    {/if}
  </div>

  <div class="flex-1 min-h-0 overflow-y-auto">
    {#if isSearching}
      <div class="py-12 flex justify-center">
        <span class="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent"></span>
      </div>
    {:else if !query.trim()}
      <p class="py-8 text-center text-sm text-muted-foreground">
        {mode === 'stat' ? 'Pick a stat to see what grants it.' : 'Type a name to search the catalog.'}
      </p>
    {:else if hasSearched}
      <div class="text-sm text-muted-foreground italic mb-2">
        Found {results.length}
        {resultMode === 'stat' ? `matches for "${searchedFor}"` : `results for "${searchedFor}"`}
        (ML {clamp(minLevel)} – {clamp(maxLevel)}{slot ? `, ${slot}` : ''}).
      </div>

      {#if results.length === 0}
        <p class="py-6 text-center text-sm text-muted-foreground">
          Nothing matched. Try widening the level window or clearing the slot filter.
        </p>
      {:else if resultMode === 'stat'}
        <div class="space-y-1">
          {#each Object.entries(grouped).sort(([a], [b]) => a.localeCompare(b)) as [bonusType, entries]}
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
                            {#if slotsLabel(entry)}
                              <span>Slots: {slotsLabel(entry)}</span>
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
      {:else}
        <div class="overflow-x-auto px-1 pb-2">
          <table class="w-full text-sm text-left">
            <thead class="text-xs text-muted-foreground uppercase bg-muted/50 border-b border-border">
              <tr>
                <th class="px-3 py-2 font-medium">Name</th>
                <th class="px-3 py-2 font-medium">Type</th>
                <th class="px-3 py-2 font-medium">ML</th>
                <th class="px-3 py-2 font-medium">Grants</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border">
              {#each results as entry (entry.sourceType + entry.sourceName)}
                <tr class="hover:bg-muted/30 transition-colors align-top">
                  <td class="px-3 py-2 font-medium">
                    <button
                      type="button"
                      on:click={() => openWikiSearch(entry.sourceName)}
                      title="Look up “{entry.sourceName}” on ddowiki — {wikiSearchURL(entry.sourceName)}"
                      class="text-left text-foreground underline decoration-dotted decoration-primary/40 underline-offset-2 hover:text-primary hover:decoration-primary transition-colors"
                    >{entry.sourceName}</button>
                    {#if entry.isRaid}
                      <span class="ml-1 rounded px-1 py-0.5 text-[9px] font-semibold bg-gold/20 text-gold border border-gold/30">Raid</span>
                    {/if}
                    {#if slotsLabel(entry)}
                      <div class="text-[11px] text-steel/70">{slotsLabel(entry)}</div>
                    {/if}
                    {#if entry.pack}
                      <div class="text-[11px] italic text-primary/70">{entry.pack}</div>
                    {/if}
                  </td>
                  <td class="px-3 py-2 text-muted-foreground capitalize">{entry.sourceType}</td>
                  <td class="px-3 py-2 text-muted-foreground">{entry.ml > 0 ? entry.ml : '—'}</td>
                  <td class="px-3 py-2 text-xs text-muted-foreground">
                    {#if entry.stats && entry.stats.length > 0}
                      <div class="flex flex-wrap gap-x-2 gap-y-0.5">
                        {#each entry.stats as stat}
                          <span>{stat}</span>
                        {/each}
                      </div>
                    {:else}
                      <span class="text-steel/50">—</span>
                    {/if}
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    {/if}
  </div>
</div>
