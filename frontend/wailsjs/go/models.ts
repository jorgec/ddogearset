export namespace main {
	
	export class OptimizationPayload {
	    max_levels: number[];
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
	
	    static createFrom(source: any = {}) {
	        return new OptimizationPayload(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.max_levels = source["max_levels"];
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
	    }
	}
	export class ResultPayload {
	    success: boolean;
	    timeTaken: number;
	    gearSet: Record<string, any>;
	    errorMessage?: string;
	
	    static createFrom(source: any = {}) {
	        return new ResultPayload(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.success = source["success"];
	        this.timeTaken = source["timeTaken"];
	        this.gearSet = source["gearSet"];
	        this.errorMessage = source["errorMessage"];
	    }
	}

}

