export namespace appdb {
	
	export class BuildSummary {
	    uuid: string;
	    name: string;
	    buildType: string;
	    weaponStyle: string;
	    maxLevel: number;
	    updatedAt: string;
	    importedFrom?: string;
	    slotCount: number;
	    orphanCount: number;
	
	    static createFrom(source: any = {}) {
	        return new BuildSummary(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.uuid = source["uuid"];
	        this.name = source["name"];
	        this.buildType = source["buildType"];
	        this.weaponStyle = source["weaponStyle"];
	        this.maxLevel = source["maxLevel"];
	        this.updatedAt = source["updatedAt"];
	        this.importedFrom = source["importedFrom"];
	        this.slotCount = source["slotCount"];
	        this.orphanCount = source["orphanCount"];
	    }
	}
	export class Orphan {
	    kind: string;
	    slot?: string;
	    name: string;
	    detail?: string;
	
	    static createFrom(source: any = {}) {
	        return new Orphan(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.kind = source["kind"];
	        this.slot = source["slot"];
	        this.name = source["name"];
	        this.detail = source["detail"];
	    }
	}
	export class ImportOutcome {
	    sourceFile: string;
	    buildUuid: string;
	    buildName: string;
	    status: string;
	    orphans?: Orphan[];
	    error?: string;
	
	    static createFrom(source: any = {}) {
	        return new ImportOutcome(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.sourceFile = source["sourceFile"];
	        this.buildUuid = source["buildUuid"];
	        this.buildName = source["buildName"];
	        this.status = source["status"];
	        this.orphans = this.convertValues(source["orphans"], Orphan);
	        this.error = source["error"];
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	
	export class RunRecord {
	    uuid: string;
	    buildUuid: string;
	    mode: string;
	    ranAt: string;
	    appVersion: string;
	    catalogCommit?: string;
	    seconds: number;
	    succeeded: boolean;
	    errorMessage?: string;
	
	    static createFrom(source: any = {}) {
	        return new RunRecord(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.uuid = source["uuid"];
	        this.buildUuid = source["buildUuid"];
	        this.mode = source["mode"];
	        this.ranAt = source["ranAt"];
	        this.appVersion = source["appVersion"];
	        this.catalogCommit = source["catalogCommit"];
	        this.seconds = source["seconds"];
	        this.succeeded = source["succeeded"];
	        this.errorMessage = source["errorMessage"];
	    }
	}

}

export namespace main {
	
	export class AugmentAssignment {
	    color: string;
	    name: string;
	
	    static createFrom(source: any = {}) {
	        return new AugmentAssignment(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.color = source["color"];
	        this.name = source["name"];
	    }
	}
	export class AlternativeItem {
	    rank: number;
	    itemName: string;
	    slot: string;
	    ml: number;
	    isRaid: boolean;
	    tierScores: Record<string, number>;
	    objectiveScore: number;
	    statDeltas: Record<string, number>;
	    augments: AugmentAssignment[];
	    filigrees: Record<string, string[]>;
	
	    static createFrom(source: any = {}) {
	        return new AlternativeItem(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.rank = source["rank"];
	        this.itemName = source["itemName"];
	        this.slot = source["slot"];
	        this.ml = source["ml"];
	        this.isRaid = source["isRaid"];
	        this.tierScores = source["tierScores"];
	        this.objectiveScore = source["objectiveScore"];
	        this.statDeltas = source["statDeltas"];
	        this.augments = this.convertValues(source["augments"], AugmentAssignment);
	        this.filigrees = source["filigrees"];
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class StatPriorityEntry {
	    stat: string;
	    tier?: number;
	    cap?: number;
	    value?: number;
	
	    static createFrom(source: any = {}) {
	        return new StatPriorityEntry(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.stat = source["stat"];
	        this.tier = source["tier"];
	        this.cap = source["cap"];
	        this.value = source["value"];
	    }
	}
	export class AlternativesPayload {
	    gearset_name: string;
	    max_level: number;
	    build_type: string;
	    weapon_style: string;
	    swashbuckling: boolean;
	    offhand_style: string;
	    weapon_damage_type?: string;
	    caster_restrict_weapon_families: boolean;
	    caster_spellpowers: string[];
	    caster_schools: string[];
	    stat_priorities: StatPriorityEntry[];
	    armor_restriction: string;
	    reserved_minor_artifact_slot: string;
	    minor_artifact_filigree_slots: number;
	    exclude_gem_of_many_facets: boolean;
	    runearm_use: boolean;
	    excluded_packs: string[];
	    owned_item_names?: string[];
	    raid_item_limit: number;
	    is_dino_artifact: boolean;
	    output_filename: string;
	    pre_equipped: Record<string, string>;
	    pre_filled_augments: Record<string, any>;
	    pre_filled_filigrees: Record<string, string[]>;
	    calculate_only: boolean;
	    max_search_time?: number;
	    mode?: string;
	    target_slot: string;
	    current_item: string;
	    equipped_items: Record<string, string>;
	    count: number;
	
	    static createFrom(source: any = {}) {
	        return new AlternativesPayload(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.gearset_name = source["gearset_name"];
	        this.max_level = source["max_level"];
	        this.build_type = source["build_type"];
	        this.weapon_style = source["weapon_style"];
	        this.swashbuckling = source["swashbuckling"];
	        this.offhand_style = source["offhand_style"];
	        this.weapon_damage_type = source["weapon_damage_type"];
	        this.caster_restrict_weapon_families = source["caster_restrict_weapon_families"];
	        this.caster_spellpowers = source["caster_spellpowers"];
	        this.caster_schools = source["caster_schools"];
	        this.stat_priorities = this.convertValues(source["stat_priorities"], StatPriorityEntry);
	        this.armor_restriction = source["armor_restriction"];
	        this.reserved_minor_artifact_slot = source["reserved_minor_artifact_slot"];
	        this.minor_artifact_filigree_slots = source["minor_artifact_filigree_slots"];
	        this.exclude_gem_of_many_facets = source["exclude_gem_of_many_facets"];
	        this.runearm_use = source["runearm_use"];
	        this.excluded_packs = source["excluded_packs"];
	        this.owned_item_names = source["owned_item_names"];
	        this.raid_item_limit = source["raid_item_limit"];
	        this.is_dino_artifact = source["is_dino_artifact"];
	        this.output_filename = source["output_filename"];
	        this.pre_equipped = source["pre_equipped"];
	        this.pre_filled_augments = source["pre_filled_augments"];
	        this.pre_filled_filigrees = source["pre_filled_filigrees"];
	        this.calculate_only = source["calculate_only"];
	        this.max_search_time = source["max_search_time"];
	        this.mode = source["mode"];
	        this.target_slot = source["target_slot"];
	        this.current_item = source["current_item"];
	        this.equipped_items = source["equipped_items"];
	        this.count = source["count"];
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class AlternativesResult {
	    success: boolean;
	    slot: string;
	    baselineTierScores: Record<string, number>;
	    alternatives: AlternativeItem[];
	    warnings?: string[];
	    errorMessage?: string;
	
	    static createFrom(source: any = {}) {
	        return new AlternativesResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.success = source["success"];
	        this.slot = source["slot"];
	        this.baselineTierScores = source["baselineTierScores"];
	        this.alternatives = this.convertValues(source["alternatives"], AlternativeItem);
	        this.warnings = source["warnings"];
	        this.errorMessage = source["errorMessage"];
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	
	export class ConsolidationReport {
	    status: string;
	    elapsedSeconds: number;
	    itemsEquipped: number;
	    duplicateSources: number;
	
	    static createFrom(source: any = {}) {
	        return new ConsolidationReport(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.status = source["status"];
	        this.elapsedSeconds = source["elapsedSeconds"];
	        this.itemsEquipped = source["itemsEquipped"];
	        this.duplicateSources = source["duplicateSources"];
	    }
	}
	export class GearsetChecksumResult {
	    hasChecksum: boolean;
	    valid: boolean;
	
	    static createFrom(source: any = {}) {
	        return new GearsetChecksumResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.hasChecksum = source["hasChecksum"];
	        this.valid = source["valid"];
	    }
	}
	export class OptimizationPayload {
	    gearset_name: string;
	    max_level: number;
	    build_type: string;
	    weapon_style: string;
	    swashbuckling: boolean;
	    offhand_style: string;
	    weapon_damage_type?: string;
	    caster_restrict_weapon_families: boolean;
	    caster_spellpowers: string[];
	    caster_schools: string[];
	    stat_priorities: StatPriorityEntry[];
	    armor_restriction: string;
	    reserved_minor_artifact_slot: string;
	    minor_artifact_filigree_slots: number;
	    exclude_gem_of_many_facets: boolean;
	    runearm_use: boolean;
	    excluded_packs: string[];
	    owned_item_names?: string[];
	    raid_item_limit: number;
	    is_dino_artifact: boolean;
	    output_filename: string;
	    pre_equipped: Record<string, string>;
	    pre_filled_augments: Record<string, any>;
	    pre_filled_filigrees: Record<string, string[]>;
	    calculate_only: boolean;
	    max_search_time?: number;
	    mode?: string;
	
	    static createFrom(source: any = {}) {
	        return new OptimizationPayload(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.gearset_name = source["gearset_name"];
	        this.max_level = source["max_level"];
	        this.build_type = source["build_type"];
	        this.weapon_style = source["weapon_style"];
	        this.swashbuckling = source["swashbuckling"];
	        this.offhand_style = source["offhand_style"];
	        this.weapon_damage_type = source["weapon_damage_type"];
	        this.caster_restrict_weapon_families = source["caster_restrict_weapon_families"];
	        this.caster_spellpowers = source["caster_spellpowers"];
	        this.caster_schools = source["caster_schools"];
	        this.stat_priorities = this.convertValues(source["stat_priorities"], StatPriorityEntry);
	        this.armor_restriction = source["armor_restriction"];
	        this.reserved_minor_artifact_slot = source["reserved_minor_artifact_slot"];
	        this.minor_artifact_filigree_slots = source["minor_artifact_filigree_slots"];
	        this.exclude_gem_of_many_facets = source["exclude_gem_of_many_facets"];
	        this.runearm_use = source["runearm_use"];
	        this.excluded_packs = source["excluded_packs"];
	        this.owned_item_names = source["owned_item_names"];
	        this.raid_item_limit = source["raid_item_limit"];
	        this.is_dino_artifact = source["is_dino_artifact"];
	        this.output_filename = source["output_filename"];
	        this.pre_equipped = source["pre_equipped"];
	        this.pre_filled_augments = source["pre_filled_augments"];
	        this.pre_filled_filigrees = source["pre_filled_filigrees"];
	        this.calculate_only = source["calculate_only"];
	        this.max_search_time = source["max_search_time"];
	        this.mode = source["mode"];
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class LoadedBuildPayload {
	    uuid: string;
	    name: string;
	    config: OptimizationPayload;
	    orphans?: appdb.Orphan[];
	
	    static createFrom(source: any = {}) {
	        return new LoadedBuildPayload(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.uuid = source["uuid"];
	        this.name = source["name"];
	        this.config = this.convertValues(source["config"], OptimizationPayload);
	        this.orphans = this.convertValues(source["orphans"], appdb.Orphan);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	
	export class RecalculationRequest {
	    gearset_name: string;
	    max_level: number;
	    build_type: string;
	    stat_priorities: StatPriorityEntry[];
	    pre_equipped: Record<string, string>;
	    pre_filled_augments: Record<string, any>;
	    pre_filled_filigrees: Record<string, string[]>;
	
	    static createFrom(source: any = {}) {
	        return new RecalculationRequest(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.gearset_name = source["gearset_name"];
	        this.max_level = source["max_level"];
	        this.build_type = source["build_type"];
	        this.stat_priorities = this.convertValues(source["stat_priorities"], StatPriorityEntry);
	        this.pre_equipped = source["pre_equipped"];
	        this.pre_filled_augments = source["pre_filled_augments"];
	        this.pre_filled_filigrees = source["pre_filled_filigrees"];
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class ReconciliationReport {
	    status: string;
	    elapsedSeconds: number;
	
	    static createFrom(source: any = {}) {
	        return new ReconciliationReport(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.status = source["status"];
	        this.elapsedSeconds = source["elapsedSeconds"];
	    }
	}
	export class TierStageReport {
	    tier: number;
	    goalValue?: number;
	    status: string;
	    proven: boolean;
	    budgetSeconds: number;
	    elapsedSeconds: number;
	    folded: number[];
	
	    static createFrom(source: any = {}) {
	        return new TierStageReport(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.tier = source["tier"];
	        this.goalValue = source["goalValue"];
	        this.status = source["status"];
	        this.proven = source["proven"];
	        this.budgetSeconds = source["budgetSeconds"];
	        this.elapsedSeconds = source["elapsedSeconds"];
	        this.folded = source["folded"];
	    }
	}
	export class TierReport {
	    stages: TierStageReport[];
	    consolidation?: ConsolidationReport;
	    reconciliation?: ReconciliationReport;
	    totalElapsedSeconds: number;
	    degraded: boolean;
	    notes: string[];
	
	    static createFrom(source: any = {}) {
	        return new TierReport(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.stages = this.convertValues(source["stages"], TierStageReport);
	        this.consolidation = this.convertValues(source["consolidation"], ConsolidationReport);
	        this.reconciliation = this.convertValues(source["reconciliation"], ReconciliationReport);
	        this.totalElapsedSeconds = source["totalElapsedSeconds"];
	        this.degraded = source["degraded"];
	        this.notes = source["notes"];
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class ResultPayload {
	    success: boolean;
	    timeTaken: number;
	    gearSet: Record<string, any>;
	    realizedStats?: Record<string, any>;
	    activeSets?: string[];
	    filigrees?: Record<string, string[]>;
	    allEffects?: Record<string, any>;
	    slots?: Record<string, any>;
	    errorMessage?: string;
	    tierReport?: TierReport;
	    tierScores?: Record<string, number>;
	    priorityTiers?: Record<string, number>;
	    unmetTier4?: string[];
	    unmatchedPriorities?: string[];
	    degraded?: boolean;
	
	    static createFrom(source: any = {}) {
	        return new ResultPayload(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.success = source["success"];
	        this.timeTaken = source["timeTaken"];
	        this.gearSet = source["gearSet"];
	        this.realizedStats = source["realizedStats"];
	        this.activeSets = source["activeSets"];
	        this.filigrees = source["filigrees"];
	        this.allEffects = source["allEffects"];
	        this.slots = source["slots"];
	        this.errorMessage = source["errorMessage"];
	        this.tierReport = this.convertValues(source["tierReport"], TierReport);
	        this.tierScores = source["tierScores"];
	        this.priorityTiers = source["priorityTiers"];
	        this.unmetTier4 = source["unmetTier4"];
	        this.unmatchedPriorities = source["unmatchedPriorities"];
	        this.degraded = source["degraded"];
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	
	export class StatSearchEntry {
	    sourceType: string;
	    sourceName: string;
	    bonusType: string;
	    value: number;
	    ml: number;
	    slots?: string[];
	    pack?: string;
	
	    static createFrom(source: any = {}) {
	        return new StatSearchEntry(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.sourceType = source["sourceType"];
	        this.sourceName = source["sourceName"];
	        this.bonusType = source["bonusType"];
	        this.value = source["value"];
	        this.ml = source["ml"];
	        this.slots = source["slots"];
	        this.pack = source["pack"];
	    }
	}
	export class StatSearchResult {
	    stat: string;
	    results: StatSearchEntry[];
	    success: boolean;
	    errorMessage?: string;
	
	    static createFrom(source: any = {}) {
	        return new StatSearchResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.stat = source["stat"];
	        this.results = this.convertValues(source["results"], StatSearchEntry);
	        this.success = source["success"];
	        this.errorMessage = source["errorMessage"];
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class StatSetPriority {
	    stat: string;
	    tier: number;
	    cap?: number;
	
	    static createFrom(source: any = {}) {
	        return new StatSetPriority(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.stat = source["stat"];
	        this.tier = source["tier"];
	        this.cap = source["cap"];
	    }
	}
	export class StatSet {
	    id: string;
	    name: string;
	    buildTypes: string[];
	    description: string;
	    notes?: string;
	    priorities: StatSetPriority[];
	
	    static createFrom(source: any = {}) {
	        return new StatSet(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.name = source["name"];
	        this.buildTypes = source["buildTypes"];
	        this.description = source["description"];
	        this.notes = source["notes"];
	        this.priorities = this.convertValues(source["priorities"], StatSetPriority);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	
	export class StatSetsFile {
	    version: number;
	    sets: StatSet[];
	
	    static createFrom(source: any = {}) {
	        return new StatSetsFile(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.version = source["version"];
	        this.sets = this.convertValues(source["sets"], StatSet);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	
	
	export class TroveInventoryResult {
	    success: boolean;
	    errorMessage?: string;
	    totalRows: number;
	    ownedNames: string[];
	
	    static createFrom(source: any = {}) {
	        return new TroveInventoryResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.success = source["success"];
	        this.errorMessage = source["errorMessage"];
	        this.totalRows = source["totalRows"];
	        this.ownedNames = source["ownedNames"];
	    }
	}
	export class TroveOwnedItem {
	    name: string;
	    minLevel: number;
	    packId?: string;
	    character?: string;
	    location?: string;
	
	    static createFrom(source: any = {}) {
	        return new TroveOwnedItem(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.name = source["name"];
	        this.minLevel = source["minLevel"];
	        this.packId = source["packId"];
	        this.character = source["character"];
	        this.location = source["location"];
	    }
	}
	export class TroveOwnedItemsResult {
	    success: boolean;
	    errorMessage?: string;
	    totalRows: number;
	    items: TroveOwnedItem[];
	
	    static createFrom(source: any = {}) {
	        return new TroveOwnedItemsResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.success = source["success"];
	        this.errorMessage = source["errorMessage"];
	        this.totalRows = source["totalRows"];
	        this.items = this.convertValues(source["items"], TroveOwnedItem);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}

}

export namespace models {
	
	export class XMLRequirement {
	    Type: string;
	    Item: string;
	
	    static createFrom(source: any = {}) {
	        return new XMLRequirement(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.Type = source["Type"];
	        this.Item = source["Item"];
	    }
	}
	export class XMLEffect {
	    Types: string[];
	    Bonus: string;
	    Item: string[];
	    AType: string;
	    Amount: string;
	    Requirements: XMLRequirement[];
	
	    static createFrom(source: any = {}) {
	        return new XMLEffect(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.Types = source["Types"];
	        this.Bonus = source["Bonus"];
	        this.Item = source["Item"];
	        this.AType = source["AType"];
	        this.Amount = source["Amount"];
	        this.Requirements = this.convertValues(source["Requirements"], XMLRequirement);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class XMLAugment {
	    Name: string;
	    Description: string;
	    Types: string[];
	    MinLevel: number;
	    Effects: XMLEffect[];
	
	    static createFrom(source: any = {}) {
	        return new XMLAugment(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.Name = source["Name"];
	        this.Description = source["Description"];
	        this.Types = source["Types"];
	        this.MinLevel = source["MinLevel"];
	        this.Effects = this.convertValues(source["Effects"], XMLEffect);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class XMLBaseDice {
	    Number: string;
	    Sides: string;
	
	    static createFrom(source: any = {}) {
	        return new XMLBaseDice(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.Number = source["Number"];
	        this.Sides = source["Sides"];
	    }
	}
	export class XMLBuff {
	    Type: string;
	    Item: string;
	    Description1: string;
	    Value1: string;
	    Value2: string;
	    BonusType: string;
	
	    static createFrom(source: any = {}) {
	        return new XMLBuff(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.Type = source["Type"];
	        this.Item = source["Item"];
	        this.Description1 = source["Description1"];
	        this.Value1 = source["Value1"];
	        this.Value2 = source["Value2"];
	        this.BonusType = source["BonusType"];
	    }
	}
	
	export class XMLEmbeddedAugment {
	    Name: string;
	    Description: string;
	    MinLevel: string;
	    Icon: string;
	    GrantAugment: string;
	    SetBonus: string;
	    Effects: XMLEffect[];
	
	    static createFrom(source: any = {}) {
	        return new XMLEmbeddedAugment(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.Name = source["Name"];
	        this.Description = source["Description"];
	        this.MinLevel = source["MinLevel"];
	        this.Icon = source["Icon"];
	        this.GrantAugment = source["GrantAugment"];
	        this.SetBonus = source["SetBonus"];
	        this.Effects = this.convertValues(source["Effects"], XMLEffect);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class XMLEquipmentSlot {
	    Slots: xml.Name[];
	
	    static createFrom(source: any = {}) {
	        return new XMLEquipmentSlot(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.Slots = this.convertValues(source["Slots"], xml.Name);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class XMLFiligree {
	    Name: string;
	    Description: string;
	    Menu: string;
	    SetName: string;
	    Effects: XMLEffect[];
	
	    static createFrom(source: any = {}) {
	        return new XMLFiligree(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.Name = source["Name"];
	        this.Description = source["Description"];
	        this.Menu = source["Menu"];
	        this.SetName = source["SetName"];
	        this.Effects = this.convertValues(source["Effects"], XMLEffect);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class XMLItemAugment {
	    Type: string;
	    SelectedAugment: string;
	    SelectedLevelIndex: string;
	    Augments: XMLEmbeddedAugment[];
	
	    static createFrom(source: any = {}) {
	        return new XMLItemAugment(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.Type = source["Type"];
	        this.SelectedAugment = source["SelectedAugment"];
	        this.SelectedLevelIndex = source["SelectedLevelIndex"];
	        this.Augments = this.convertValues(source["Augments"], XMLEmbeddedAugment);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class XMLItem {
	    Name: string;
	    Description: string;
	    MinLevel: number;
	    EquipmentSlot: XMLEquipmentSlot;
	    DropLocations: string[];
	    ItemAugments: XMLItemAugment[];
	    MinorArtifact?: string;
	    Icon: string;
	    Material: string;
	    SetBonuses: string[];
	    Buffs: XMLBuff[];
	    Effects: XMLEffect[];
	    Weapon: string;
	    AttackModifier: string;
	    DamageModifier: string;
	    DRBypass: string[];
	    WeaponDamage: string;
	    BaseDice?: XMLBaseDice;
	    CriticalMultiplier: string;
	    CriticalThreatRange: string;
	    Armor: string;
	    ArmorBonus: string;
	    ShieldBonus: string;
	    MaximumDexterityBonus: string;
	    ArcaneSpellFailure: string;
	    ArmorCheckPenalty: string;
	    pack_id?: string;
	    wiki_url?: string;
	    is_raid?: boolean;
	    raid_name?: string;
	
	    static createFrom(source: any = {}) {
	        return new XMLItem(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.Name = source["Name"];
	        this.Description = source["Description"];
	        this.MinLevel = source["MinLevel"];
	        this.EquipmentSlot = this.convertValues(source["EquipmentSlot"], XMLEquipmentSlot);
	        this.DropLocations = source["DropLocations"];
	        this.ItemAugments = this.convertValues(source["ItemAugments"], XMLItemAugment);
	        this.MinorArtifact = source["MinorArtifact"];
	        this.Icon = source["Icon"];
	        this.Material = source["Material"];
	        this.SetBonuses = source["SetBonuses"];
	        this.Buffs = this.convertValues(source["Buffs"], XMLBuff);
	        this.Effects = this.convertValues(source["Effects"], XMLEffect);
	        this.Weapon = source["Weapon"];
	        this.AttackModifier = source["AttackModifier"];
	        this.DamageModifier = source["DamageModifier"];
	        this.DRBypass = source["DRBypass"];
	        this.WeaponDamage = source["WeaponDamage"];
	        this.BaseDice = this.convertValues(source["BaseDice"], XMLBaseDice);
	        this.CriticalMultiplier = source["CriticalMultiplier"];
	        this.CriticalThreatRange = source["CriticalThreatRange"];
	        this.Armor = source["Armor"];
	        this.ArmorBonus = source["ArmorBonus"];
	        this.ShieldBonus = source["ShieldBonus"];
	        this.MaximumDexterityBonus = source["MaximumDexterityBonus"];
	        this.ArcaneSpellFailure = source["ArcaneSpellFailure"];
	        this.ArmorCheckPenalty = source["ArmorCheckPenalty"];
	        this.pack_id = source["pack_id"];
	        this.wiki_url = source["wiki_url"];
	        this.is_raid = source["is_raid"];
	        this.raid_name = source["raid_name"];
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	
	
	export class XMLSetTier {
	    EquippedCount: string;
	    Description: string;
	    Effects: XMLEffect[];
	
	    static createFrom(source: any = {}) {
	        return new XMLSetTier(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.EquippedCount = source["EquippedCount"];
	        this.Description = source["Description"];
	        this.Effects = this.convertValues(source["Effects"], XMLEffect);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class XMLSetBonus {
	    Type: string;
	    Icon: string;
	    Tiers: XMLSetTier[];
	
	    static createFrom(source: any = {}) {
	        return new XMLSetBonus(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.Type = source["Type"];
	        this.Icon = source["Icon"];
	        this.Tiers = this.convertValues(source["Tiers"], XMLSetTier);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}

}

export namespace xml {
	
	export class Name {
	    Space: string;
	    Local: string;
	
	    static createFrom(source: any = {}) {
	        return new Name(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.Space = source["Space"];
	        this.Local = source["Local"];
	    }
	}

}

