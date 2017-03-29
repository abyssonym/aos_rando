from randomtools.tablereader import (
    TableObject, get_global_label, tblpath, addresses)
from randomtools.utils import (
    classproperty, mutate_normal, shuffle_bits, get_snes_palette_transformer,
    write_multi, utilrandom as random)
from randomtools.interface import (
    get_outfile, get_seed, get_flags, run_interface, rewrite_snes_meta,
    clean_and_write, finish_interface)
from randomtools.itemrouter import ItemRouter
from collections import defaultdict
from os import path
from time import time
from collections import Counter
import string


VERSION = 1
ALL_OBJECTS = None
DEBUG_MODE = False
RESEED_COUNTER = 0
ITEM_NAMES = {}


def reseed():
    global RESEED_COUNTER
    RESEED_COUNTER += 1
    seed = get_seed()
    random.seed(seed + (RESEED_COUNTER**2))


def get_item_names():
    if ITEM_NAMES:
        return ITEM_NAMES

    for line in open(path.join(tblpath, "item_names.txt")):
        line = line.strip()
        if not line or line[0] == '#':
            continue
        index, name = line.split(' ', 1)
        ITEM_NAMES[int(index, 0x10)] = name.strip()

    return get_item_names()


class MonsterObject(TableObject):
    flag = "d"
    flag_description = "enemy souls and drops"
    intershuffle_attributes = [("soul_type", "soul"),
                               "common_drop",
                               "rare_drop"]

    def mutate(self):
        for attr in ["common_drop", "rare_drop"]:
            value = getattr(self, attr)
            if value == 0:
                continue
            i = ItemObject.superget(value)
            i = i.get_similar()
            value = (value & 0xFF00) | i.superindex
            setattr(self, attr, value)


class ItemObject(TableObject):
    @property
    def rank(self):
        if self.price == 0:
            rank = 1000000
        else:
            rank = self.price
        return rank + random.random()

    @property
    def name(self):
        index = self.index
        if isinstance(self, ConsumableObject):
            index |= 0x200
        if isinstance(self, WeaponObject):
            index |= 0x300
        elif isinstance(self, ArmorObject):
            index |= 0x400
        return get_item_names()[index]

    @classmethod
    def superget(cls, index):
        return (ConsumableObject.every +
                WeaponObject.every +
                ArmorObject.every)[index]

    @property
    def superindex(self):
        index = self.index
        if isinstance(self, WeaponObject) or isinstance(self, ArmorObject):
            index += len(ConsumableObject.every)
        if isinstance(self, ArmorObject):
            index += len(WeaponObject.every)
        return index


class ConsumableObject(ItemObject): pass
class WeaponObject(ItemObject): pass
class ArmorObject(ItemObject): pass


class TreasureObject(TableObject):
    flag = "i"
    flag_description = "item and ability locations"

    @property
    def name(self):
        index = ((self.item_type) << 8) | self.item_index
        return get_item_names()[index]

    @classmethod
    def get_by_pointer(cls, pointer):
        return [t for t in TreasureObject.every if t.pointer == pointer][0]

    @classmethod
    def randomize_all(cls):
        ir = ItemRouter(path.join(tblpath, "requirements.txt"))
        ir.assign_everything()
        souls = [(t.item_type, t.item_index) for t in TreasureObject.every
                 if t.item_type >= 5]

        # save for later when picking items
        item_types = [t.item_type for t in TreasureObject.every]

        for pointer, item in sorted(ir.assignments.items()):
            pointer = int(pointer, 0x10)
            item = int(item, 0x10)
            item_type = item >> 8
            item_index = item & 0xFF
            if (item_type, item_index) in souls:
                souls.remove((item_type, item_index))

        for item_type, item_index in souls:
            item = "%x" % ((item_type << 8) | item_index)
            ir.assign_item(item, relaxed=True)

        done_treasures = set([])
        done_items = set([])
        for pointer, item in sorted(ir.assignments.items()):
            pointer = int(pointer, 0x10)
            item = int(item, 0x10)
            item_type = item >> 8
            item_index = item & 0xFF
            t = TreasureObject.get_by_pointer(pointer)
            t.item_type = item_type
            t.item_index = item_index
            done_treasures.add(t)
            done_items.add((item_type, item_index))

        remaining_treasures = [t for t in TreasureObject.every
                               if t not in done_treasures]
        random.shuffle(remaining_treasures)
        max_rank = max(ir.location_ranks)
        for t in remaining_treasures:
            rank = ir.get_location_rank("%x" % t.pointer)
            if rank is None:
                rank = ((random.random() + random.random() + random.random())
                        * max_rank / 3.0)
            ratio = float(rank) / max_rank
            while True:
                low = random.uniform(
                        0.0, random.uniform(0.0, random.uniform(0.0, 1.0)))
                high = random.uniform(random.uniform(0.0, 1.0), 1.0)
                if low > high:
                    low, high = high, low
                score = (ratio * high) + ((1-ratio) * low)
                item_type = random.choice(item_types)
                if item_type == 1:
                    # money
                    max_index = 6
                    item_index = int(round(score * max_index))
                elif 2 <= item_type <= 4:
                    if item_type == 2:
                        # consumables
                        objects = ConsumableObject.ranked
                    elif item_type == 3:
                        # weapons
                        objects = WeaponObject.ranked
                    elif item_type == 4:
                        # armor
                        objects = ArmorObject.ranked
                    max_index = len(objects)-1
                    index = int(round(score * max_index))
                    chosen = objects[index]
                    item_index = chosen.index
                elif item_type >= 5:
                    # souls
                    m = random.choice(MonsterObject.every)
                    item_type = m.soul_type = 5
                    item_index = m.soul
                if item_type >= 3 and (item_type, item_index) in done_items:
                    continue
                t.item_type = item_type
                t.item_index = item_index
                done_items.add((item_type, item_index))
                break


if __name__ == "__main__":
    try:
        print ('You are using the Castlevania: Aria of Sorrow '
               'randomizer version %s.' % VERSION)
        print

        ALL_OBJECTS = [g for g in globals().values()
                       if isinstance(g, type) and issubclass(g, TableObject)
                       and g not in [TableObject]]
        run_interface(ALL_OBJECTS, snes=True)
        hexify = lambda x: "{0:0>2}".format("%x" % x)
        numify = lambda x: "{0: >3}".format(x)
        minmax = lambda x: (min(x), max(x))

        if DEBUG_MODE:
            pass

        clean_and_write(ALL_OBJECTS)
        finish_interface()
    except Exception, e:
        print "ERROR: %s" % e
        raw_input("Press Enter to close this program.")
