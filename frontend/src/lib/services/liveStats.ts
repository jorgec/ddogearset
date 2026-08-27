import { fetchItem } from './itemCatalog';
import type { models } from '../../../wailsjs/go/models';

export interface LiveStatEntry {
    stat: string;
    total: number;
}

function buffStatLabel(b: models.XMLBuff): string {
    return (b.Item && b.Item.trim()) || b.Type || '';
}

function formatLabel(label: string): string {
    if (label.includes(' ') || label.length <= 3) return label;
    return label.replace(/([a-z])([A-Z])/g, '$1 $2');
}

export async function computeLiveStats(preEquipped: Record<string, string>): Promise<LiveStatEntry[]> {
    const itemNames = [...new Set(Object.values(preEquipped).filter(Boolean))];
    if (itemNames.length === 0) return [];

    const items = await Promise.all(
        itemNames.map(name => fetchItem(name).catch(() => null))
    );

    const byStatAndType = new Map<string, Map<string, number[]>>();
    const labels = new Map<string, string>();

    for (const item of items) {
        if (!item?.Name) continue;
        for (const b of item.Buffs ?? []) {
            if (!b.Value1?.trim() || !b.BonusType?.trim()) continue;
            const raw = buffStatLabel(b);
            if (!raw) continue;
            const value = parseFloat(b.Value1);
            if (isNaN(value)) continue;

            const key = raw.toLowerCase();
            if (!labels.has(key)) labels.set(key, formatLabel(raw));

            if (!byStatAndType.has(key)) byStatAndType.set(key, new Map());
            const typeMap = byStatAndType.get(key)!;
            const btKey = b.BonusType.trim().toLowerCase();
            if (!typeMap.has(btKey)) typeMap.set(btKey, []);
            typeMap.get(btKey)!.push(value);
        }
    }

    // DDO stacking: highest value per (stat, bonusType) wins.
    // Exception: "Stacking" bonus type always adds.
    const entries: LiveStatEntry[] = [];
    for (const [key, typeMap] of byStatAndType) {
        let total = 0;
        for (const [bonusType, values] of typeMap) {
            if (bonusType === 'stacking') {
                total += values.reduce((s, v) => s + v, 0);
            } else {
                total += Math.max(...values);
            }
        }
        entries.push({
            stat: labels.get(key)!,
            total: Math.round(total * 100) / 100,
        });
    }

    entries.sort((a, b) => b.total - a.total);
    return entries;
}
