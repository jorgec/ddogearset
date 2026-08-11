<script lang="ts">
  import { resultStore, configStore, isOptimizing, hydrateConfigFromSlots, showToast,
           troveImportStore, defaultConfig } from '$lib/store';
  import { GetAvailableItems, GetItemDetails, GetAvailableFiligrees, RecalculateGearset } from '../../../../wailsjs/go/main/App';
  import type { models, main } from '../../../../wailsjs/go/models';
  import { main as mainModels } from '../../../../wailsjs/go/models';
  import ItemDetail from './ItemDetail.svelte';
  import SlotAlternatives from './SlotAlternatives.svelte';
  import FiligreeEditor from './FiligreeEditor.svelte';

  let editorTab: 'gear' | 'filigrees' = 'gear';

  const baseSlots = ['Helmet', 'Necklace', 'Trinket', 'Cloak', 'Belt', 'Ring_1', 'Ring_2', 'Gloves', 'Boots', 'Bracers', 'Armor', 'Goggles', 'Weapon1', 'Weapon2'];

  // docs/SLOT_ALTERNATIVES_UI_SPEC.md — the slot currently showing the
  // alternatives drawer, or null when closed.
  let alternativesSlot: string | null = null;

  let selectedSlot: string | null = null;
  let availableItems: models.XMLItem[] = [];
  let isFetchingItems = false;
  let searchQuery = "";
  let searchTimeout: any;
  
  let editingFiligreeIdx: number | null = null;
  let editingFiligreeType: "weapon" | "artifact" | null = null;
  let availableFiligrees: models.XMLFiligree[] = [];
  let isFetchingFiligrees = false;
  let filigreeSearchQuery = "";
  let filigreeSearchTimeout: any;
  let filigreeSetFilter = "";
  
  $: uniqueFiligreeSets = Array.from(new Set(availableFiligrees.map(f => f.SetName))).filter(Boolean).sort();
  $: filteredFiligrees = availableFiligrees.filter(f => !filigreeSetFilter || f.SetName === filigreeSetFilter);
  
  let selectedItemDetails: models.XMLItem | null = null;
  
  function isWeapon(item: models.XMLItem) {
      if (!item.EquipmentSlot || !item.EquipmentSlot.Slots) return false;
      return item.EquipmentSlot.Slots.includes("Weapon1" as any) || item.EquipmentSlot.Slots.includes("Weapon2" as any) || item.EquipmentSlot.Slots.includes("Weapon" as any);
  }

  function getArtifactFiligreeCount(item: models.XMLItem) {
      if (item.MinorArtifact === undefined) return 0;
      if (item.Name === "Epic Voice of the Master") return 1;
      if (item.MinLevel >= 33) return 5;
      if (item.MinLevel >= 31) return 4;
      if (item.MinLevel >= 30) return 3;
      return 1;
  }
  
  function getWeaponFiligreeCount(item: models.XMLItem) {
      if (!isWeapon(item)) return 0;
      if (item.MinLevel < 20) return 0;
      return 10; // Sentient weapons can hold up to 10 with max sparks. We'll show 10 slots.
  }
  
  $: if (!$resultStore) {
      $resultStore = { success: true, timeTaken: 0, gearSet: {}, realizedStats: {}, activeSets: [], filigrees: {} } as unknown as main.ResultPayload;
  }
  $: if ($resultStore && !$resultStore.gearSet) {
      $resultStore.gearSet = {};
  }

  // Auto-hydrate pre_equipped/pre_filled_augments/pre_filled_filigrees whenever a new
  // solved/loaded gearset's per-slot detail becomes available (Auto Solver run or
  // .ddogearset file load), so items placed here show their augments/filigrees
  // immediately instead of only after clicking "Calculate Stats". Only fills gaps —
  // never overwrites anything already manually edited (see hydrateConfigFromSlots).
  let hydratedSlotsRef: Record<string, any> | undefined = undefined;
  $: if ($resultStore?.slots && $resultStore.slots !== hydratedSlotsRef) {
      hydratedSlotsRef = $resultStore.slots;
      const hydrated = hydrateConfigFromSlots($configStore, $resultStore.slots);
      if (hydrated) {
          $configStore.pre_equipped = hydrated.pre_equipped;
          $configStore.pre_filled_augments = hydrated.pre_filled_augments;
          $configStore.pre_filled_filigrees = hydrated.pre_filled_filigrees;
      }
  }

  async function handleSlotClick(slot: string) {
      selectedSlot = slot;
      searchQuery = ""; // reset search on new slot click
      await fetchItems(slot, "");
  }
  
  async function fetchItems(slot: string, query: string) {
      isFetchingItems = true;
      const maxLvl = $configStore.max_level || 34;
      
      try {
          const res = await GetAvailableItems(slot, maxLvl, query);
          // Minor artifact enforcement
          const currentArtifacts = Object.values($resultStore.gearSet).filter(iName => {
              // we don't have isMinor readily available without fetching details, but assuming we can check if it's already an artifact.
              // For simplicity, we just show all items and enforce on select.
              return false; // To fully enforce, we'd need item details of all equipped.
          });
          availableItems = res || [];
      } catch(e) {
          console.error(e);
      } finally {
          isFetchingItems = false;
      }
  }

  function handleSearchInput() {
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(() => {
          if (selectedSlot) {
              fetchItems(selectedSlot, searchQuery);
          }
      }, 300);
  }

  async function handleItemClick(slot: string, itemName: string) {
      selectedSlot = slot;
      availableItems = [];
      editingFiligreeIdx = null;
      editingFiligreeType = null;
      try {
          selectedItemDetails = await GetItemDetails(itemName);
      } catch(e) {
          console.error(e);
      }
  }

  async function assignMinorArtifact(item: models.XMLItem) {
      if (!selectedSlot) return;
      const baseSlot = selectedSlot.replace('_1', '').replace('_2', '');
      $configStore.reserved_minor_artifact_slot = baseSlot;
      $configStore.is_dino_artifact = item.Name.toLowerCase().includes('dinosaur');
      
      for (const [slot, name] of Object.entries($resultStore.gearSet)) {
          if (slot !== selectedSlot && name) {
              try {
                  const details = await GetItemDetails(name as string);
                  if (details && details.MinorArtifact !== undefined && details.MinorArtifact !== null) {
                      clearSlot(slot);
                  }
              } catch (e) {
                  console.error(e);
              }
          }
      }
  }

  async function handleMinorArtifactToggle(checked: boolean) {
      if (!selectedItemDetails || !selectedSlot) return;
      if (checked) {
          selectedItemDetails.MinorArtifact = "";
          await assignMinorArtifact(selectedItemDetails);
      } else {
          selectedItemDetails.MinorArtifact = undefined as any;
          const baseSlot = selectedSlot.replace('_1', '').replace('_2', '');
          if ($configStore.reserved_minor_artifact_slot === baseSlot) {
              $configStore.reserved_minor_artifact_slot = "Any";
          }
      }
  }

  async function selectItem(item: models.XMLItem) {
      if (!selectedSlot) return;
      
      const isMinor = item.MinorArtifact !== undefined && item.MinorArtifact !== null;
      if (isMinor) {
          await assignMinorArtifact(item);
      }

      $resultStore.gearSet[selectedSlot] = item.Name;
      $configStore.pre_equipped[selectedSlot] = item.Name;
      // Also clear existing augments for this slot if item changes
      if ($configStore.pre_filled_augments[selectedSlot]) {
          delete $configStore.pre_filled_augments[selectedSlot];
      }
      $resultStore.gearSet = {...$resultStore.gearSet};
      $configStore.pre_equipped = {...$configStore.pre_equipped};
      $configStore.pre_filled_augments = {...$configStore.pre_filled_augments};
      selectedItemDetails = item;
      availableItems = []; // Close dropdown
  }

  function clearSlot(slot: string) {
      delete $resultStore.gearSet[slot];
      delete $configStore.pre_equipped[slot];
      if ($configStore.pre_filled_augments[slot]) {
          delete $configStore.pre_filled_augments[slot];
      }
      $resultStore.gearSet = {...$resultStore.gearSet};
      $configStore.pre_equipped = {...$configStore.pre_equipped};
      $configStore.pre_filled_augments = {...$configStore.pre_filled_augments};
      if (selectedSlot === slot) {
          selectedItemDetails = null;
      }
  }
  
  async function openFiligreePicker(idx: number, type: "weapon" | "artifact") {
      editingFiligreeIdx = idx;
      editingFiligreeType = type;
      filigreeSearchQuery = "";
      filigreeSetFilter = "";
      await fetchFiligrees("");
  }
  
  async function fetchFiligrees(query: string) {
      isFetchingFiligrees = true;
      try {
          availableFiligrees = await GetAvailableFiligrees(query) || [];
      } catch (e) {
          console.error(e);
      } finally {
          isFetchingFiligrees = false;
      }
  }
  
  function handleFiligreeSearchInput() {
      clearTimeout(filigreeSearchTimeout);
      filigreeSearchTimeout = setTimeout(() => {
          fetchFiligrees(filigreeSearchQuery);
      }, 300);
  }
  
  function selectFiligree(idx: number, fil: models.XMLFiligree) {
      if (!editingFiligreeType) return;
      if (!$configStore.pre_filled_filigrees[editingFiligreeType]) {
          $configStore.pre_filled_filigrees[editingFiligreeType] = [];
      }
      while ($configStore.pre_filled_filigrees[editingFiligreeType].length <= idx) {
          $configStore.pre_filled_filigrees[editingFiligreeType].push("");
      }
      $configStore.pre_filled_filigrees[editingFiligreeType][idx] = fil.Name;
      $configStore.pre_filled_filigrees = {...$configStore.pre_filled_filigrees};
      editingFiligreeIdx = null;
      editingFiligreeType = null;
  }
  
  function clearFiligree(idx: number, type: "weapon" | "artifact") {
      if (!$configStore.pre_filled_filigrees[type]) return;
      $configStore.pre_filled_filigrees[type][idx] = "";
      $configStore.pre_filled_filigrees = {...$configStore.pre_filled_filigrees};
  }

  // --- Check Inventory (docs/0.5.0/UI_CHANGES_0_5_0.md §3) -----------------
  //
  // Badges every socketed item against the loaded Trove CSV. The comparison is
  // EXACT and CASE-SENSITIVE on purpose: that is precisely what the solver does
  // (`name not in owned_names`), and anything looser — trimming, case-folding,
  // fuzzy matching — would badge an item green that the solver then refuses to
  // use when "restrict to owned" is on. The button would be lying about the one
  // thing it exists to tell you.
  let inventoryChecked = false;

  $: inventoryLoaded = ($troveImportStore.ownedNames?.length ?? 0) > 0;

  // Badges clear themselves if the CSV is unloaded. A stale green dot pointing
  // at an inventory that is no longer loaded is worse than no dot.
  $: if (!inventoryLoaded && inventoryChecked) inventoryChecked = false;

  // Reactive, so swapping an item re-badges it without pressing the button
  // again.
  $: ownedNameSet = new Set($troveImportStore.ownedNames ?? []);

  function ownershipOf(itemName: string | undefined): 'owned' | 'missing' | null {
      if (!inventoryChecked || !itemName) return null;
      return ownedNameSet.has(itemName) ? 'owned' : 'missing';
  }

  function checkInventory() {
      if (!inventoryLoaded) return;
      inventoryChecked = true;
      const equipped = baseSlots
          .map((slot) => $resultStore?.gearSet?.[slot])
          .filter((n): n is string => !!n);
      const owned = equipped.filter((n) => ownedNameSet.has(n)).length;
      showToast(
          `${owned} of ${equipped.length} equipped item(s) are in ${$troveImportStore.fileName || 'your inventory'}.`,
          owned === equipped.length ? 'success' : 'info'
      );
  }

  // --- New ------------------------------------------------------------------
  //
  // Resets the BUILD: parameters, gear, and the last result. Deliberately does
  // NOT unload the Trove inventory — that is a file the user loaded, not part
  // of the build, and making them re-import it to start a second gearset would
  // be its own annoyance.
  //
  // Confirmed first, because it discards work that is only recoverable if it
  // happened to be saved.
  // Asks with an action toast, not window.confirm — Wails' webview never shows
  // the latter and returns false, which would make this button silently do
  // nothing (exactly what happened to Delete).
  function startNew() {
      const hasWork = Object.keys($configStore.pre_equipped ?? {}).length > 0 ||
                      ($configStore.stat_priorities?.length ?? 0) > 0;
      if (!hasWork) {
          resetToNewBuild();
          return;
      }
      showToast(
          'Start a new build? This clears your priorities, settings and equipped ' +
          'gear. Anything you have saved stays in the database.',
          'info',
          [{ label: 'Start New', onClick: resetToNewBuild }]
      );
  }

  function resetToNewBuild() {
      $configStore = defaultConfig();
      $resultStore = null as unknown as main.ResultPayload;
      selectedItemDetails = null;
      selectedSlot = null;
      availableItems = [];
      alternativesSlot = null;
      inventoryChecked = false;
      showToast('Started a new build.', 'success');
  }

  // Clears the GEARSET only — never the parameters.
  //
  // Priorities, build type, level cap, armour restriction and the rest survive,
  // because the common use is "keep what I am solving for, let the solver fill
  // the slots again". Wiping those too is what New is for, and conflating the
  // two would make the safer button the destructive one.
  function clearAll() {
      $resultStore = { success: true, timeTaken: 0, gearSet: {}, realizedStats: {}, activeSets: [], filigrees: {} } as unknown as main.ResultPayload;
      $configStore.pre_equipped = {};
      $configStore.pre_filled_augments = {};
      $configStore.pre_filled_filigrees = { weapon: [], artifact: [] };
      selectedItemDetails = null;
      selectedSlot = null;
      availableItems = [];
  }

  // The one place a full configuration is narrowed to what a recalculation
  // may see. Mirrors Go's RecalculationRequestFrom and Summary.svelte's
  // recalculationRequest; kept to one function here for the same reason it is
  // one function there.
  function recalculationRequest(config: main.OptimizationPayload): main.RecalculationRequest {
      return mainModels.RecalculationRequest.createFrom({
          gearset_name: config.gearset_name,
          max_level: config.max_level,
          build_type: config.build_type,
          stat_priorities: config.stat_priorities,
          pre_equipped: config.pre_equipped,
          pre_filled_augments: config.pre_filled_augments,
          pre_filled_filigrees: config.pre_filled_filigrees,
      });
  }

  async function calculateGearSet() {
      $isOptimizing = true;
      try {
          // Non-destructive/read-only recompute: fill in pre_equipped/
          // pre_filled_augments/pre_filled_filigrees from the last known
          // solved/loaded gearset for anything not already manually edited
          // this session. See docs/ENGINEERING.md "Known Issues".
          const hydrated = hydrateConfigFromSlots($configStore, $resultStore?.slots);
          if (hydrated) {
              $configStore.pre_equipped = hydrated.pre_equipped;
              $configStore.pre_filled_augments = hydrated.pre_filled_augments;
              $configStore.pre_filled_filigrees = hydrated.pre_filled_filigrees;
          }
          // A recalculation takes a NARROWED request, not the whole config:
          // RecalculationRequest has nowhere to put a search restriction
          // (armor_restriction, weapon_style, ...), so none can reach an
          // evaluation of gear the user already has (0.5.1 Phase 4/5).
          const res = await RecalculateGearset(recalculationRequest($configStore));
          if (res && res.success) {
              $resultStore = res;
              showToast('Stats recalculated.', 'success');
          } else {
              showToast(res?.errorMessage || 'Calculation failed.', 'error');
          }
      } catch (e) {
          console.error(e);
          showToast('Calculation failed: ' + e, 'error');
      } finally {
          $isOptimizing = false;
      }
  }

  // --- Redesign helpers (docs/DASHBOARD_REDESIGN_SPEC.md) ------------------

  // §6 — the picker/detail is a focus-stealing modal now rather than a side
  // pane: this panel lives in a 25%-wide column that cannot host both. Gated
  // on there actually being something to show, so clearing a slot (which
  // leaves `selectedSlot` set) can't pop an empty dialog.
  $: modalOpen = selectedSlot !== null
      && (selectedItemDetails !== null || availableItems.length > 0 || searchQuery !== "" || isFetchingItems);

  function closeModal() {
      selectedSlot = null;
      availableItems = [];
      searchQuery = "";
      selectedItemDetails = null;
  }

  // §4.2 — "item name is displayed in a distinct color based on rarity
  // (e.g. Purple for Epic, Orange for Legendary)". DDO encodes exactly that
  // in the item name itself ("Legendary …" / "Epic …"), with minimum level as
  // the authoritative fallback for anything not prefixed — so this reads real
  // data rather than inventing a rarity field the corpus doesn't have.
  function rarityClass(name: string, ml: number): string {
      const n = (name || '').toLowerCase();
      if (n.startsWith('legendary') || ml >= 30) return 'text-gold';
      if (n.startsWith('epic') || ml >= 20) return 'text-[#A78BFA]';
      return 'text-vellum';
  }

  const SLOT_ICON: Record<string, string> = {
      Helmet: 'M4 13a8 8 0 0116 0v4H4z',
      Necklace: 'M7 4a5 5 0 0010 0M12 9v3m0 0a2.5 2.5 0 100 5 2.5 2.5 0 000-5z',
      Trinket: 'M12 3l2.4 5.6L20 11l-5.6 2.4L12 19l-2.4-5.6L4 11l5.6-2.4z',
      Cloak: 'M8 3l4 4 4-4 4 6-3 12H7L4 9z',
      Belt: 'M3 10h18v4H3zM10 9v6h4V9z',
      Ring_1: 'M12 9a4.5 4.5 0 100 9 4.5 4.5 0 000-9zM10 6.5L12 3l2 3.5',
      Ring_2: 'M12 9a4.5 4.5 0 100 9 4.5 4.5 0 000-9zM10 6.5L12 3l2 3.5',
      Gloves: 'M7 12V6.5a1.5 1.5 0 013 0V11m0-4.5a1.5 1.5 0 013 0V11m0-3a1.5 1.5 0 013 0v6a5 5 0 01-5 5h-2a4 4 0 01-4-4v-3',
      Boots: 'M8 3v9c0 3 1 5 4 5h6v-3l-4-2V3z',
      Bracers: 'M6 5h12l-2 6 2 8H8l2-8z',
      Armor: 'M12 3l8 3v6c0 5-4 8-8 9-4-1-8-4-8-9V6z',
      Goggles: 'M3 10h18v3a3 3 0 01-3 3h-1a3 3 0 01-3-3h-4a3 3 0 01-3 3H6a3 3 0 01-3-3z',
      Weapon1: 'M14 3l7 7-9 9-3-3 2-2-2-2 2-2-2-2z',
      Weapon2: 'M14 3l7 7-9 9-3-3 2-2-2-2 2-2-2-2z',
  };
</script>

<div class="panel h-full flex flex-col min-h-0">
  <!-- Panel header -->
  <div class="px-3 pt-3 pb-2 shrink-0">
    <div class="flex items-baseline justify-between gap-2">
      <div class="flex items-center gap-1">
        <button
          type="button"
          on:click={() => (editorTab = 'gear')}
          class="belt-stud px-2.5 py-1 text-xs {editorTab === 'gear' ? 'belt-stud-active' : ''}"
        >Gear</button>
        <button
          type="button"
          on:click={() => (editorTab = 'filigrees')}
          class="belt-stud px-2.5 py-1 text-xs {editorTab === 'filigrees' ? 'belt-stud-active' : ''}"
        >Filigrees</button>
      </div>
      <div class="flex items-center gap-1.5">
        <button
          on:click={calculateGearSet}
          disabled={$isOptimizing}
          class="px-2 py-1 text-[11px] rounded bg-carved text-vellum hover:bg-carved/70 hover:shadow-press border border-carved transition-all disabled:opacity-50 flex items-center gap-1"
          title="Recalculate stats from the currently socketed gear"
        >
          {#if $isOptimizing}
            <span class="h-2.5 w-2.5 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
          {/if}
          Calculate
        </button>
        <button
          on:click={checkInventory}
          disabled={$isOptimizing || !inventoryLoaded}
          class="px-2 py-1 text-[11px] rounded bg-carved text-vellum hover:bg-carved/70 hover:shadow-press border border-carved transition-all disabled:opacity-40"
          title={inventoryLoaded
            ? 'Badge each socketed item against your loaded Trove inventory'
            : 'Load a Trove inventory CSV first'}
        >Check Inventory</button>
        <button
          on:click={clearAll}
          disabled={$isOptimizing}
          class="px-2 py-1 text-[11px] rounded text-steel hover:text-blood hover:bg-carved transition-colors border border-transparent hover:border-carved disabled:opacity-50"
          title="Clear every socket — your priorities and settings are kept"
        >Clear</button>
        <button
          on:click={startNew}
          disabled={$isOptimizing}
          class="px-2 py-1 text-[11px] rounded text-steel hover:text-vellum hover:bg-carved transition-colors border border-transparent hover:border-carved disabled:opacity-50"
          title="Start a new build — clears priorities, settings and gear"
        >New</button>
      </div>
    </div>
    <div class="gold-rule mt-2"></div>
  </div>

  <!-- §4.2 — slots presented as physical sockets waiting to be filled.
       Both tabs stay mounted; only visibility toggles, matching the
       drawer/readout convention elsewhere so switching tabs never discards
       an in-flight filigree search or the socket list's scroll position. -->
  <div class:hidden={editorTab !== 'gear'} class="flex-1 min-h-0 overflow-y-auto px-2 pb-3 space-y-1.5">
    {#each baseSlots as slot}
      {@const itemName = $resultStore?.gearSet?.[slot]}
      {@const detail = $resultStore?.slots?.[slot]}
      {@const ml = detail?.item?.ml ?? 0}
      {@const owned = ownershipOf(itemName)}
      <div class="group relative flex items-center gap-2 px-2 py-1.5 transition-colors
                  {itemName ? 'socket-filled' : 'socket'}
                  {selectedSlot === slot ? 'ring-1 ring-gold/60' : ''}">
        <!-- item-type glyph -->
        <svg class="h-4 w-4 shrink-0 {itemName ? 'text-gold/80' : 'text-carved'}"
             viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"
             stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d={SLOT_ICON[slot] ?? 'M12 3l9 9-9 9-9-9z'} />
        </svg>

        <div class="min-w-0 flex-1">
          <div class="text-[10px] uppercase tracking-wider text-steel/70 leading-none flex items-center gap-1.5">
            <span>{slot.replace('_1', ' 1').replace('_2', ' 2')}</span>
            {#if owned}
              <span class="inline-flex items-center gap-1 normal-case tracking-normal
                           {owned === 'owned' ? 'text-emerald-400' : 'text-blood'}"
                    title={owned === 'owned'
                      ? 'In your loaded Trove inventory'
                      : 'NOT in your loaded Trove inventory'}>
                <span class="h-1.5 w-1.5 rounded-full {owned === 'owned' ? 'bg-emerald-400' : 'bg-blood'}"></span>
                {owned === 'owned' ? 'owned' : 'not owned'}
              </span>
            {/if}
          </div>
          {#if itemName}
            <button
              class="mt-0.5 block w-full text-left text-xs font-medium truncate hover:underline {rarityClass(itemName, ml)}"
              on:click={() => handleItemClick(slot, itemName)}
              title={itemName}
            >{itemName}</button>
          {:else}
            <button
              class="mt-0.5 block w-full text-left text-xs italic text-steel/50 hover:text-gold transition-colors"
              on:click={() => handleSlotClick(slot)}
            >{slot.startsWith('Weapon') ? 'Engrave Relic' : 'Socket Empty'}</button>
          {/if}
        </div>

        <!-- actions: quiet until the socket is hovered/focused -->
        <div class="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity shrink-0">
          <button on:click={() => alternativesSlot = slot}
                  class="p-1 rounded text-steel hover:text-gold hover:bg-carved transition-colors"
                  title="Find alternatives for this slot">
            <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                 stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/></svg>
          </button>
          {#if itemName}
            <button on:click={() => clearSlot(slot)}
                    class="p-1 rounded text-steel hover:text-blood hover:bg-carved transition-colors"
                    title="Clear this socket">
              <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                   stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
            </button>
          {/if}
        </div>
      </div>
    {/each}
  </div>

  <div class:hidden={editorTab !== 'filigrees'} class="flex-1 min-h-0 overflow-y-auto px-3 pb-3">
    <FiligreeEditor />
  </div>
</div>

<!-- §6 — item selection/detail modal: blurred backdrop, Obsidian body. -->
{#if modalOpen}
  <div
    class="fixed inset-0 z-50 flex items-center justify-center p-6 bg-void/70 backdrop-blur-md"
    role="button"
    tabindex="-1"
    on:click|self={closeModal}
    on:keydown={(e) => e.key === 'Escape' && closeModal()}
  >
    <div class="panel w-full max-w-3xl max-h-[85vh] flex flex-col shadow-2xl">
      <div class="flex items-center justify-between px-4 py-3 shrink-0">
        <h3 class="panel-title text-sm">
          {selectedItemDetails ? selectedItemDetails.Name : `Select ${(selectedSlot ?? '').replace('_1', ' 1').replace('_2', ' 2')}`}
        </h3>
        <button on:click={closeModal} class="p-1 rounded text-steel hover:text-vellum hover:bg-carved transition-colors" title="Close">
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
        </button>
      </div>
      <div class="gold-rule mx-4 shrink-0"></div>

      <div class="flex-1 min-h-0 overflow-y-auto p-4">
        {#if selectedItemDetails}
          <ItemDetail
              itemName={selectedItemDetails.Name}
              slot={selectedSlot}
              slotDetail={selectedSlot ? ($resultStore?.slots?.[selectedSlot] ?? null) : null}
              mode="edit"
              on:minorArtifactToggle={(e) => handleMinorArtifactToggle(e.detail.checked)}
          />
        {:else}
          <input
            type="text"
            bind:value={searchQuery}
            on:input={handleSearchInput}
            placeholder="Search names or raw XML data..."
            class="w-full h-10 rounded-md border border-input bg-void px-3 py-2 text-sm placeholder:text-steel/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring mb-3"
          />
          {#if isFetchingItems}
            <p class="text-steel animate-pulse text-sm">Consulting the archives…</p>
          {:else if availableItems.length === 0}
            <p class="text-steel text-sm">No items found for this slot and level range.</p>
          {:else}
            <div class="space-y-1.5">
              {#each availableItems as item}
                <button
                  on:click={async () => { await selectItem(item); closeModal(); }}
                  class="w-full text-left px-3 py-2 rounded bg-void/60 border border-carved hover:border-gold/40 hover:bg-carved/40 transition-colors"
                >
                  <div class="text-sm font-medium {rarityClass(item.Name, item.MinLevel)}">{item.Name}</div>
                  <div class="text-[11px] text-steel">ML {item.MinLevel}</div>
                </button>
              {/each}
            </div>
          {/if}
        {/if}
      </div>
    </div>
  </div>
{/if}

{#if alternativesSlot}
  {@const currentAlternativesSlot = alternativesSlot}
  <SlotAlternatives targetSlot={currentAlternativesSlot} onClose={() => alternativesSlot = null} />
{/if}
