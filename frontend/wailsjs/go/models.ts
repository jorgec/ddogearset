export namespace main {
	
	export class OptimizationPayload {
	    gearset_name: string;
	    max_level: number;
	    build_type: string;
	    weapon_style: string;
	    swashbuckling: boolean;
	    offhand_style: string;
	    caster_spellpowers: string[];
	    caster_schools: string[];
	    stat_priorities: Record<string, number>;
	    armor_restriction: string;
	    reserved_minor_artifact_slot: string;
	    minor_artifact_filigree_slots: number;
	    exclude_gem_of_many_facets: boolean;
	    runearm_use: boolean;
	    excluded_packs: string[];
	    raid_item_limit: number;
	    is_dino_artifact: boolean;
	    output_filename: string;
	    pre_equipped: Record<string, string>;
	    pre_filled_augments: Record<string, string[]>;
	    pre_filled_filigrees: Record<string, string[]>;
	    calculate_only: boolean;
	
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
	        this.caster_spellpowers = source["caster_spellpowers"];
	        this.caster_schools = source["caster_schools"];
	        this.stat_priorities = source["stat_priorities"];
	        this.armor_restriction = source["armor_restriction"];
	        this.reserved_minor_artifact_slot = source["reserved_minor_artifact_slot"];
	        this.minor_artifact_filigree_slots = source["minor_artifact_filigree_slots"];
	        this.exclude_gem_of_many_facets = source["exclude_gem_of_many_facets"];
	        this.runearm_use = source["runearm_use"];
	        this.excluded_packs = source["excluded_packs"];
	        this.raid_item_limit = source["raid_item_limit"];
	        this.is_dino_artifact = source["is_dino_artifact"];
	        this.output_filename = source["output_filename"];
	        this.pre_equipped = source["pre_equipped"];
	        this.pre_filled_augments = source["pre_filled_augments"];
	        this.pre_filled_filigrees = source["pre_filled_filigrees"];
	        this.calculate_only = source["calculate_only"];
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
	    errorMessage?: string;
	
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
	        this.errorMessage = source["errorMessage"];
	    }
	}

}

export namespace models {
	
	export class XMLAugment {
	    Name: string;
	    Description: string;
	    Types: string[];
	    MinLevel: number;
	
	    static createFrom(source: any = {}) {
	        return new XMLAugment(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.Name = source["Name"];
	        this.Description = source["Description"];
	        this.Types = source["Types"];
	        this.MinLevel = source["MinLevel"];
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
	
	    static createFrom(source: any = {}) {
	        return new XMLFiligree(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.Name = source["Name"];
	        this.Description = source["Description"];
	        this.Menu = source["Menu"];
	        this.SetName = source["SetName"];
	    }
	}
	export class XMLItemAugment {
	    Type: string;
	
	    static createFrom(source: any = {}) {
	        return new XMLItemAugment(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.Type = source["Type"];
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

