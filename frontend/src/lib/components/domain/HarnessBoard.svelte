<script lang="ts">
  import { HARNESS_TILES } from '$lib/harness';
  import { resultStore, configStore, pickerSlot, alternativesSlotStore } from '$lib/store';
  import { rarityClass } from '$lib/harness';
  import harnessActive from '../../../assets/images/harness/harness.jpg';
  import harnessDisabled from '../../../assets/images/harness/harness-disabled.jpg';

  export let onSwitchToSummary: () => void;

  $: gearSet = $resultStore?.gearSet ?? {};
  $: slots = $resultStore?.slots ?? {};

  // Phase 11 §5 Step 3.1 — Weapon2 lock. Mirrors GearsetEditor's weapon2Locked.
  $: weapon2Locked = (() => {
      const ws = $configStore.weapon_style;
      if (ws === 'Two Handed Fighting' || ws === 'Bow') return true;
      if (ws === 'Single Weapon Fighting') {
          if ($configStore.swashbuckling) return false;
          const os = $configStore.offhand_style ?? '';
          return os === '' || os === 'None' || os === 'Empty';
      }
      return false;
  })();

  function slotLabel(slot: string): string {
      return slot.replace('_1', ' 1').replace('_2', ' 2');
  }
</script>

<div class="h-full flex items-start justify-center overflow-hidden">
  <div
    class="relative bg-no-repeat"
    style="
      background-image: url({harnessDisabled});
      background-size: 100% 100%;
      aspect-ratio: 412 / 731;
      height: 100%;
    "
  >
    {#each HARNESS_TILES as tile}
      {#if tile.slot === null}
        <!-- Summary toggle tile -->
        <button
          type="button"
          class="absolute bg-no-repeat cursor-pointer hover:ring-2 hover:ring-gold/50 rounded-sm transition-all"
          style="{tile.positionStyle};{tile.bgStyle};background-image:url({harnessActive})"
          on:click={onSwitchToSummary}
          aria-label="Switch to Summary view"
          title="Switch to Summary view"
        ></button>
      {:else}
        {@const itemName = gearSet[tile.slot]}
        {@const detail = slots[tile.slot]}
        {@const ml = detail?.item?.ml ?? 0}
        {@const isLocked = tile.slot === 'Weapon2' && weapon2Locked}
        <button
          type="button"
          class="absolute bg-no-repeat rounded-sm transition-all
                 {itemName ? 'hover:ring-2 hover:ring-gold/60 cursor-pointer' : 'hover:ring-2 hover:ring-arcane/40 cursor-pointer'}
                 {isLocked ? 'opacity-40 cursor-not-allowed' : ''}
                 group"
          style="{tile.positionStyle};{itemName ? `${tile.bgStyle};background-image:url(${harnessActive})` : ''}"
          on:click={() => {
              if (isLocked) return;
              $pickerSlot = tile.slot;
          }}
          aria-label="{slotLabel(tile.slot)}{itemName ? ': ' + itemName : ': empty'}"
          title={isLocked ? 'Weapon2 is locked by the current weapon style' : (itemName ? `${itemName} (ML ${ml})` : `${slotLabel(tile.slot)} — empty`)}
        >
          {#if itemName}
            <!-- Name plate -->
            <span
              class="absolute bottom-0 left-0 right-0 px-1 py-0.5 text-[9px] leading-tight font-medium truncate
                     bg-void/70 backdrop-blur-sm rounded-b-sm {rarityClass(itemName, ml)}"
            >{itemName}</span>
          {/if}
          {#if isLocked}
            <span class="absolute inset-0 flex items-center justify-center text-steel/60">
              <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                   stroke-linecap="round" stroke-linejoin="round">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0110 0v4"/>
              </svg>
            </span>
          {/if}
          <!-- Alternatives gear icon on hover -->
          {#if itemName && !isLocked}
            <button
              type="button"
              class="absolute top-0.5 right-0.5 p-0.5 rounded bg-void/60 text-steel
                     opacity-0 group-hover:opacity-100 hover:text-gold transition-all"
              on:click|stopPropagation={() => { $alternativesSlotStore = tile.slot; }}
              title="Find alternatives"
              aria-label="Find alternatives for {slotLabel(tile.slot)}"
            >
              <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                   stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="3"/>
                <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>
              </svg>
            </button>
          {/if}
        </button>
      {/if}
    {/each}
  </div>
</div>
