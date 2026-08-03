import os
import xml.etree.ElementTree as ET

def parse_quests(base_dir):
    quests = {}
    try:
        tree = ET.parse(os.path.join(base_dir, 'Quests.xml'))
        for quest_node in tree.findall('.//Quest'):
            name = quest_node.findtext('Name')
            pack = quest_node.findtext('AdventurePack')
            is_raid = quest_node.find('IsRaid') is not None
            if name:
                quests[name] = {'AdventurePack': pack, 'is_raid': is_raid}
    except Exception:
        pass
    return quests
