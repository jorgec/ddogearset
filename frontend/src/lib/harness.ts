// Sprite-sheet geometry for the DDO character-sheet harness board.
// docs/PHASE12_PLAN.md §2.1 — measured from the real assets.

export const SHEET_W = 412;
export const SHEET_H = 731;
export const TILE_W = 96;
export const TILE_H = 98;

const COL_X = [32, 158, 285] as const;
const ROW_Y = [54, 185, 315, 446, 603] as const;

// Reading order, top-left → bottom-right.  `null` = decorative / non-gear.
export const HARNESS_LAYOUT: (string | null)[][] = [
    ['Goggles',  'Helmet',  'Necklace'],
    ['Cloak',    'Armor',   'Trinket'],
    ['Bracers',  'Belt',    'Gloves'],
    ['Ring_1',   'Boots',   'Ring_2'],
    ['Weapon1',  'Weapon2', null],
];

export interface HarnessTile {
    slot: string | null;
    row: number;
    col: number;
    // Ready-to-use inline style for the absolutely-positioned tile button.
    positionStyle: string;
    // Ready-to-use inline style for the colour-sheet background on filled slots.
    bgStyle: string;
}

function pct(n: number, d: number): string {
    return (n / d * 100).toFixed(4) + '%';
}

function buildTiles(): HarnessTile[] {
    const tiles: HarnessTile[] = [];
    for (let row = 0; row < HARNESS_LAYOUT.length; row++) {
        for (let col = 0; col < HARNESS_LAYOUT[row].length; col++) {
            const x = COL_X[col];
            const y = ROW_Y[row];

            const positionStyle = [
                `left:${pct(x, SHEET_W)}`,
                `top:${pct(y, SHEET_H)}`,
                `width:${pct(TILE_W, SHEET_W)}`,
                `height:${pct(TILE_H, SHEET_H)}`,
            ].join(';');

            // background-position percentage: pct × (container − image) = offset
            // container = tile size, image = sheet size, so:
            //   bgX = x / (SHEET_W - TILE_W), bgY = y / (SHEET_H - TILE_H)
            const bgX = pct(x, SHEET_W - TILE_W);
            const bgY = pct(y, SHEET_H - TILE_H);
            const bgSizeX = pct(SHEET_W, TILE_W);
            const bgSizeY = pct(SHEET_H, TILE_H);

            const bgStyle = [
                `background-position:${bgX} ${bgY}`,
                `background-size:${bgSizeX} ${bgSizeY}`,
            ].join(';');

            tiles.push({
                slot: HARNESS_LAYOUT[row][col],
                row,
                col,
                positionStyle,
                bgStyle,
            });
        }
    }
    return tiles;
}

export const HARNESS_TILES = buildTiles();

export const HARNESS_GEAR_SLOTS = HARNESS_TILES
    .map(t => t.slot)
    .filter((s): s is string => s !== null)
    .sort();

const BASE_SLOTS = [
    'Armor', 'Belt', 'Boots', 'Bracers', 'Cloak', 'Gloves', 'Goggles',
    'Helmet', 'Necklace', 'Ring_1', 'Ring_2', 'Trinket', 'Weapon1', 'Weapon2',
];
if (HARNESS_GEAR_SLOTS.join(',') !== BASE_SLOTS.join(',')) {
    throw new Error(
        'HARNESS_GEAR_SLOTS does not match baseSlots — harness.ts and GearsetEditor.svelte are out of sync'
    );
}

export function rarityClass(name: string, ml: number): string {
    const n = (name || '').toLowerCase();
    if (n.startsWith('legendary') || ml >= 30) return 'text-gold';
    if (n.startsWith('epic') || ml >= 20) return 'text-[#A78BFA]';
    return 'text-vellum';
}
