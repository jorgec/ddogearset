<script lang="ts">
  // Caster Tier-1 prefill — docs/HARD_REQUIRED_SLOTS_SPEC.md §4.
  //
  // Deliberately a one-time "Apply" action, NOT a standing reactive sync.
  // This exact feature existed once before as a live sync (the now-dead
  // caster_spellpowers/caster_schools fields — see
  // $lib/data/statPriorities.ts's migrateLegacyCasterFields doc comment) and
  // was removed because keeping two representations of the same intent
  // continuously in sync had a real bug: unchecking a school left its
  // priority behind forever. This mirrors StatSetPicker.svelte's applySet
  // pattern instead — click to add, Undo to revert, no ongoing binding.
  import { configStore, showToast, statSetUndoSnapshot } from '$lib/store';
  import { canAddStat, cloneLanes, findTier, hydrateLanes, serializePriorities } from '$lib/data/statPriorities';

  // Same wire convention as $lib/data/statTaxonomy.ts's Spellpower/Elemental
  // and Spell Schools (Spell DC) categories — reused exactly, not reinvented,
  // so these stats match the same normalize_stat_name paths already proven
  // elsewhere in the app.
  const ELEMENTS: [string, string][] = [
    ['Fire', 'fire spellpower'],
    ['Cold', 'cold spellpower'],
    ['Acid', 'acid spellpower'],
    ['Electric', 'electric spellpower'],
    ['Sonic', 'sonic spellpower'],
    ['Force', 'force spellpower'],
    ['Positive', 'positive spellpower'],
    ['Negative', 'negative spellpower'],
    ['Poison', 'poison spellpower'],
    ['Repair', 'repair spellpower'],
  ];
  // Ability score stats match via AbilityBonus buffs' <Item> field (e.g.
  // <Item>Intelligence</Item>) — the literal name is the correct wire stat.
  const MAIN_STATS = ['Intelligence', 'Charisma', 'Wisdom'];
  const SCHOOLS = ['Evocation', 'Necromancy', 'Enchantment', 'Conjuration', 'Divination', 'Abjuration', 'Transmutation', 'Illusion'];

  let selectedElements: string[] = [];
  let selectedMainStat = '';
  let selectedSchools: string[] = [];

  function toggle(list: string[], value: string): string[] {
    return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
  }

  function apply() {
    const statsToAdd: string[] = [
      ...selectedElements,
      ...(selectedMainStat ? [selectedMainStat] : []),
      // normalize_stat_name already folds "spell focus" matching into any
      // priority containing "dc" (optimizer.py's normalize_stat_name) — a
      // separate "<School> Spell Focus" entry would just match overlapping
      // data a second time, so one entry per school is enough.
      ...selectedSchools.map((s) => `${s.toLowerCase()} spelldc`),
    ];

    if (statsToAdd.length === 0) {
      showToast('Select at least one element, main stat, or spell school first.', 'error');
      return;
    }

    const snapshot = ($configStore.stat_priorities ?? []).map((e) => ({ ...e }));
    const lanes = cloneLanes(hydrateLanes($configStore.stat_priorities));
    let added = 0;
    let kept = 0;
    let blocked = 0;

    for (const stat of statsToAdd) {
      if (findTier(lanes, stat) !== null) {
        kept++;
        continue;
      }
      if (!canAddStat(lanes, stat).ok) {
        blocked++;
        continue;
      }
      lanes[1].push({ stat });
      added++;
    }

    $configStore.stat_priorities = serializePriorities(lanes);
    $statSetUndoSnapshot = snapshot;

    const blockedText = blocked > 0 ? ` ${blocked} skipped (conflict).` : '';
    showToast(
      `Added ${added} to Tier 1 — ${kept} already in your list.${blockedText}`,
      'success',
      [
        {
          label: 'Undo',
          onClick: () => {
            $configStore.stat_priorities = snapshot;
            $statSetUndoSnapshot = null;
          },
        },
      ]
    );
  }
</script>

<div class="space-y-4">
  <p class="text-[10px] text-muted-foreground">
    Select your caster's elemental damage type(s), main stat, and spell school(s) below, then
    apply them to Tier 1. This adds to your current priority list — it never removes anything,
    and re-applying is safe (already-placed stats are left untouched).
  </p>

  <div class="space-y-2">
    <p class="text-sm font-medium leading-none">Elemental Damage Type</p>
    <div class="grid grid-cols-2 md:grid-cols-5 gap-2">
      {#each ELEMENTS as [label, stat]}
        <label class="flex items-center space-x-2 text-sm cursor-pointer">
          <input
            type="checkbox"
            checked={selectedElements.includes(stat)}
            on:change={() => (selectedElements = toggle(selectedElements, stat))}
            class="h-4 w-4 rounded border-input bg-transparent text-primary focus:ring-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background"
          />
          <span class="text-foreground">{label}</span>
        </label>
      {/each}
    </div>
  </div>

  <div class="space-y-2">
    <label class="text-sm font-medium leading-none" for="caster-main-stat">Main Stat</label>
    <select id="caster-main-stat" bind:value={selectedMainStat} class="flex h-10 w-full max-w-xs rounded-md border border-input bg-transparent px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
      <option value="" class="bg-background text-foreground">None</option>
      {#each MAIN_STATS as stat}
        <option value={stat} class="bg-background text-foreground">{stat}</option>
      {/each}
    </select>
  </div>

  <div class="space-y-2">
    <p class="text-sm font-medium leading-none">Spell School(s)</p>
    <div class="grid grid-cols-2 md:grid-cols-4 gap-2">
      {#each SCHOOLS as school}
        <label class="flex items-center space-x-2 text-sm cursor-pointer">
          <input
            type="checkbox"
            checked={selectedSchools.includes(school)}
            on:change={() => (selectedSchools = toggle(selectedSchools, school))}
            class="h-4 w-4 rounded border-input bg-transparent text-primary focus:ring-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background"
          />
          <span class="text-foreground">{school}</span>
        </label>
      {/each}
    </div>
  </div>

  <button
    type="button"
    on:click={apply}
    class="px-3 py-1.5 text-sm bg-secondary text-secondary-foreground hover:bg-secondary/80 rounded transition-colors"
  >
    Apply to Tier 1
  </button>
</div>
