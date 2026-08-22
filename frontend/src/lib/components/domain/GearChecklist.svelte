<script lang="ts">
  import { configStore, resultStore, troveImportStore } from '$lib/store';
  import type { SlotDetail, TroveOwnedItem } from '$lib/store';
  import { fetchItem } from '$lib/services/itemCatalog';
  import { openWikiSearch } from '$lib/wiki';

  const SLOT_ORDER = [
    'Helmet', 'Goggles', 'Necklace', 'Trinket', 'Cloak', 'Belt',
    'Ring_1', 'Ring_2', 'Gloves', 'Boots', 'Bracers', 'Armor',
    'Weapon1', 'Weapon2',
  ];

  interface ChecklistEntry {
      slot: string;
      name: string;
      dropLocations: string[];
      pack: string | null;
      isRaid: boolean;
  }

  let entries: ChecklistEntry[] = [];

  $: slots = ($resultStore as any)?.slots as Record<string, SlotDetail> | undefined;
  $: gearSet = ($resultStore as any)?.gearSet as Record<string, string> | undefined;

  $: troveNames = new Set(
      ($troveImportStore.ownedNames ?? []).map((n: string) => n.toLowerCase())
  );

  $: checklist = $configStore.checklist_owned ?? {};

  $: {
      const items = gearSet ?? {};
      const ordered = SLOT_ORDER.filter(s => items[s]);
      loadEntries(ordered, items);
  }

  async function loadEntries(orderedSlots: string[], items: Record<string, string>) {
      const result: ChecklistEntry[] = [];
      for (const slot of orderedSlots) {
          const name = items[slot];
          if (!name) continue;
          const slotDetail = slots?.[slot];
          const pack = slotDetail?.item?.pack ?? null;
          const isRaid = slotDetail?.item?.is_raid ?? false;

          let dropLocations: string[] = [];
          try {
              const detail = await fetchItem(name);
              if (detail?.DropLocations?.length) {
                  dropLocations = detail.DropLocations;
              }
          } catch {}

          result.push({ slot, name, dropLocations, pack, isRaid });
      }
      entries = result;
  }

  // Where each owned item actually sits — character and bank/location, comma
  // joined by the importer when one name turns up in several places. Keyed
  // lower-case to match troveNames, which is what decides ownership here.
  $: troveInfoByName = new Map<string, TroveOwnedItem>(
      ($troveImportStore.items ?? []).map((i: TroveOwnedItem) => [i.name.toLowerCase(), i])
  );

  // Derived rather than called from the markup: an isOwned(name) call there
  // would not re-run when a CSV is loaded, because Svelte tracks the
  // identifiers an expression mentions, not what the callee reads.
  $: ownedByName = new Map(
      entries.map(e => [e.name, e.name in checklist
          ? checklist[e.name]
          : troveNames.has(e.name.toLowerCase())])
  );

  // Present only when the CSV vouches for the item, so a hand-ticked checkbox
  // never invents a location it cannot know. Both are maps for the same reason
  // ownedByName is: the markup has to read values, not call helpers.
  $: inTroveByName = new Map(
      entries.map(e => [e.name, troveNames.has(e.name.toLowerCase())])
  );

  $: whereByName = new Map(
      entries.map(e => [e.name, troveWhere(troveInfoByName.get(e.name.toLowerCase()))])
  );

  function troveWhere(info: TroveOwnedItem | undefined): string | null {
      if (!info) return null;
      if (info.character && info.location) return `${info.character} — ${info.location}`;
      return info.character || info.location || null;
  }

  function isOwned(name: string): boolean {
      if (name in checklist) return checklist[name];
      return troveNames.has(name.toLowerCase());
  }

  function toggleOwned(name: string) {
      const current = isOwned(name);
      const next = { ...($configStore.checklist_owned ?? {}) };
      next[name] = !current;
      $configStore.checklist_owned = next;
  }

  function slotLabel(slot: string): string {
      return slot.replace('_', ' ');
  }

  function questFromDrop(drop: string): string | null {
      const trimmed = drop.trim();
      if (!trimmed) return null;
      if (trimmed.toLowerCase().startsWith('turn in')) return null;
      if (trimmed.toLowerCase().startsWith('upgrade ')) return null;
      const commaIdx = trimmed.indexOf(',');
      return commaIdx > 0 ? trimmed.substring(0, commaIdx).trim() : trimmed;
  }

  $: ownedCount = [...ownedByName.values()].filter(Boolean).length;
</script>

<div class="panel flex flex-col h-full overflow-hidden">
  <div class="px-4 pt-3 pb-2 shrink-0 border-b border-border/50">
    <h2 class="panel-title text-sm">Gear Checklist</h2>
    {#if entries.length > 0}
      <p class="text-[11px] text-steel mt-0.5">
        {ownedCount} / {entries.length} items owned
      </p>
    {:else}
      <p class="text-[11px] text-steel mt-0.5">Run a solve to populate the checklist.</p>
    {/if}
  </div>

  <div class="flex-1 min-h-0 overflow-y-auto">
    {#if entries.length === 0}
      <div class="flex items-center justify-center h-full text-sm text-muted-foreground">
        No gearset to display.
      </div>
    {:else}
      <div class="divide-y divide-border/30">
        {#each entries as entry (entry.slot)}
          {@const owned = ownedByName.get(entry.name) ?? false}
          {@const inTrove = inTroveByName.get(entry.name) ?? false}
          {@const where = inTrove ? whereByName.get(entry.name) : null}
          <div class="px-4 py-2.5 hover:bg-muted/20 transition-colors">
            <div class="flex items-start gap-3">
              <label class="flex items-center shrink-0 mt-0.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={owned}
                  on:change={() => toggleOwned(entry.name)}
                  class="h-4 w-4 rounded border-border accent-primary cursor-pointer"
                />
              </label>

              <div class="flex-1 min-w-0">
                <div class="flex items-baseline gap-2">
                  <span class="text-sm font-medium {owned ? 'text-vitality' : 'text-foreground'}">
                    {entry.name}
                  </span>
                  {#if entry.isRaid}
                    <span class="shrink-0 rounded px-1 py-0.5 text-[9px] font-semibold bg-gold/20 text-gold border border-gold/30">Raid</span>
                  {/if}
                </div>

                <div class="text-[11px] text-muted-foreground mt-0.5">
                  <span class="text-steel/70">{slotLabel(entry.slot)}</span>
                  {#if entry.pack}
                    <span class="mx-1 text-border">·</span>
                    <span class="italic text-primary/60">{entry.pack}</span>
                  {/if}
                </div>

                {#if inTrove}
                  <div class="mt-0.5 flex items-baseline gap-1.5 text-[11px]">
                    <span class="shrink-0 rounded px-1 py-0.5 text-[9px] font-semibold bg-vitality/15 text-vitality border border-vitality/30">In Trove</span>
                    {#if where}
                      <span class="truncate text-steel/70" title={where}>{where}</span>
                    {/if}
                  </div>
                {/if}

                {#if entry.dropLocations.length > 0}
                  <div class="mt-1 space-y-0.5">
                    {#each entry.dropLocations as drop}
                      {@const quest = questFromDrop(drop)}
                      <div class="text-[11px] text-muted-foreground flex items-start gap-1">
                        <span class="shrink-0 text-steel/50 mt-px">↳</span>
                        <span class="break-words">
                          {#if quest}
                            <button
                              type="button"
                              on:click={() => openWikiSearch(quest)}
                              title="Look up {quest} on ddowiki"
                              class="text-left underline decoration-dotted decoration-primary/40 underline-offset-2 hover:text-primary hover:decoration-primary transition-colors"
                            >{quest}</button>{#if drop.length > quest.length}<span class="text-steel/50">{drop.substring(quest.length)}</span>{/if}
                          {:else}
                            {drop}
                          {/if}
                        </span>
                      </div>
                    {/each}
                  </div>
                {/if}
              </div>
            </div>
          </div>
        {/each}
      </div>
    {/if}
  </div>
</div>
