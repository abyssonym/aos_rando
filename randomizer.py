from randomtools.tablereader import (
    TableObject, get_global_label, tblpath, addresses)
from randomtools.utils import (
    classproperty, mutate_normal, shuffle_bits, get_snes_palette_transformer,
    write_multi, utilrandom as random)
from randomtools.interface import (
    get_outfile, get_seed, get_flags, get_activated_codes,
    run_interface, rewrite_snes_meta,
    clean_and_write, finish_interface)
from randomtools.itemrouter import ItemRouter
from os import path


VERSION = 5
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

    @property
    def intershuffle_valid(self):
        if self.soul_type == 0 and self.soul == 0:
            return False
        if "i" not in get_flags() and self.index in [0x5F, 0x68]:
            return False
        return True

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

    @classproperty
    def every(self):
        if self is ItemObject:
            return (ConsumableObject.every +
                    WeaponObject.every +
                    ArmorObject.every)
        return super(ItemObject, self).every


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


class ShopIndexObject(TableObject): pass


def route_items():
    hard_mode = "hard" in get_activated_codes()
    bat_mode = "bat" in get_activated_codes()
    if hard_mode:
        print "HARD MODE ACTIVATED"
        ir = ItemRouter(path.join(tblpath, "hard_requirements.txt"))
    elif bat_mode:
        print "BAT MODE ACTIVATED"
        ir = ItemRouter(path.join(tblpath, "bat_requirements.txt"))
    else:
        ir = ItemRouter(path.join(tblpath, "requirements.txt"))

    if hard_mode:
        aggression=4
    else:
        aggression=3

    while True:
        ir.assign_everything(aggression=aggression)
        if hard_mode:
            bat_location = ir.get_assigned_location("602")
            assert bat_location is not None
            hippo_location = ir.get_assigned_location("805")
            malphas_location = ir.get_assigned_location("803")
            if (hippo_location and
                    ir.get_location_rank(bat_location) <
                    ir.get_location_rank(hippo_location)):
                ir.clear_assignments()
                continue
            if (malphas_location and
                    ir.get_location_rank(bat_location) <
                    ir.get_location_rank(malphas_location)):
                ir.clear_assignments()
                continue
        break

    souls = [(t.item_type, t.item_index) for t in TreasureObject.every
             if t.item_type >= 5]
    souls += [(0x8, 0x04)]  # kicker skeleton

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
        if bat_mode or (hard_mode and random.choice([True, False])):
            continue
        ir.assign_item(item, aggression=aggression)

    if hard_mode and (8, 0x05) in souls:
        bat_location = ir.get_assigned_location("602")
        hippo_location = ir.get_assigned_location("805")
        assert bat_location is not None
        if (hippo_location and
                ir.get_location_rank(bat_location) >
                ir.get_location_rank(hippo_location)):
            ir.unassign_item("805")

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
    oops_all_souls = 'oopsallsouls' in get_activated_codes()
    if oops_all_souls:
        print "OOPS ALL SOULS CODE ACTIVATED"
    for t in remaining_treasures:
        rank = ir.get_location_rank("%x" % t.pointer)
        if rank is None:
            rank = ((random.random() + random.random() + random.random())
                    * max_rank / 3.0)
        ratio = float(rank) / max_rank
        while True:
            if oops_all_souls:
                item_type = 5
            else:
                item_type = random.choice(item_types)
            if item_type < 5:
                low = random.uniform(0.0, random.uniform(0.0, 1.0))
                high = random.uniform(0.0, 1.0)
                if hard_mode:
                    low = random.uniform(0.0, low)
                else:
                    high = random.uniform(high, 1.0)
                if low > high:
                    low, high = high, low
                score = (ratio * high) + ((1-ratio) * low)

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
                if 3 <= item_type <= 4:
                    objects = [o for o in objects
                               if (item_type, o.index) not in done_items]
                max_index = len(objects)-1
                index = int(round(score * max_index))
                chosen = objects[index]
                item_index = chosen.index
            elif item_type >= 5:
                # souls
                m = random.choice(MonsterObject.every)
                item_type = m.soul_type + 5
                item_index = m.soul
                if item_type == 5 and item_index == 0:
                    continue
            if ((item_type >= 3 or
                    item_type == 1 or
                    (item_type == 2 and item_index >= 0x1a)) and
                    (item_type, item_index) in done_items):
                continue
            t.item_type = item_type
            t.item_index = item_index
            done_items.add((item_type, item_index))
            break

    # replace boss souls to prevent softlocks
    winged = [m for m in MonsterObject.every
              if m.soul_type == 0 and m.soul == 1][0]
    kicker = [m for m in MonsterObject.every
              if m.soul_type == 3 and m.soul == 4][0]
    if hard_mode:
        replaceable = [kicker, winged]
    else:
        replaceable = [winged, kicker]
    legion = MonsterObject.get(0x6c)
    balore = MonsterObject.get(0x6d)
    bosses = [legion, balore]
    random.shuffle(bosses)
    for boss in bosses:
        if boss is legion:
            locations = [0x51d051, 0x51d825]
            souls = set([(8, 0x03), (8, 0x05), (6, 0x02)])
        elif boss is balore:
            locations = [0x51f1d1, 0x51f8b5, 0x51f909]
            souls = set([(8, 0x03), (8, 0x05), (6, 0x03), (6, 0x02)])
        else:
            raise Exception
        locations = set([
            (t.get_by_pointer(l).item_type, t.get_by_pointer(l).item_index)
            for l in locations])
        if locations & souls:
            continue
        soulstrs = dict([((a, b), "{0}{1:0>2}".format("%x" % a, "%x" % b))
                         for (a, b) in souls])
        souls = [s for s in souls if ir.get_item_rank(soulstrs[s]) is not None]
        souls = sorted(
            souls, key=lambda s: (ir.get_item_rank(soulstrs[s]),
                                  random.random()))
        soul_type, soul = souls.pop(0)
        replacement = replaceable.pop(0)
        replacement.soul_type = boss.soul_type
        replacement.soul = boss.soul
        boss.soul_type = soul_type
        boss.soul = soul


def enable_cutscene_skip():
    # 0x1AF8 is the byte in SRAM that saves whether the game has been beaten
    # (#03 if so) and therefore cutscenes can be skipped.
    # This byte is copied to 02000060 when the game is turned on.
    # When Start is pressed during a cutscene, the byte is loaded from
    # memory at 0x5B56C.
    # This patch changes it to a simple MOV r0, #03 instruction.
    f = open(get_outfile(), "r+b")
    f.seek(0x5B56C)
    f.write("".join(map(chr, [0x03, 0x20])))
    f.close()


if __name__ == "__main__":
    try:
        print ('You are using the Castlevania: Aria of Sorrow '
               'item randomizer version %s.' % VERSION)
        print

        ALL_OBJECTS = [g for g in globals().values()
                       if isinstance(g, type) and issubclass(g, TableObject)
                       and g not in [TableObject]]

        codes = {
            'oopsallsouls': ['oopsallsouls', 'oops all souls',
                               'oops_all_souls'],
            'bat': ['batcompany', 'bat_company', 'bat company'],
            'hard': 'hard',
        }
        run_interface(ALL_OBJECTS, snes=True, codes=codes)

        activated_codes = get_activated_codes()
        if ('i' in get_flags() or "oopsallsouls" in activated_codes
                or "bat" in activated_codes or "hard" in activated_codes):
            route_items()

        hexify = lambda x: "{0:0>2}".format("%x" % x)
        numify = lambda x: "{0: >3}".format(x)
        minmax = lambda x: (min(x), max(x))

        if DEBUG_MODE:
            for m in MonsterObject.every:
                m.hp = 1
                m.atk = 1
                m.xp = 1000

            soul_pointers = {
                    # castle entrance
                    0x510bf9: 0x603,
                    0x510c11: 0x805,
                    0x510c1d: 0x803,
                    0x5109dd: 0x801,
                    0x510af1: 0x802,
                    0x510afd: 0x601,
                    # reservoir
                    0x51cbf5: 0x701,
                    0x51cd5d: 0x702,
                    0x51cd39: random.choice([0x612, 0x613, 0x614]),
                    # past creaking skull
                    0x510ed5: 0x602,
                    0x511145: 0x52c,
                    0x511565: 0x707,
                }
            done_pointers = []
            for p, s in soul_pointers.items():
                item_type = s >> 8
                item_index = s & 0xFF
                t = TreasureObject.get_by_pointer(p)
                t.item_type = item_type
                t.item_index = item_index
                done_pointers.append(p)

            souls = sorted(set([(e.soul_type, e.soul)
                                for e in MonsterObject.every
                                if e.soul_type > 0 or e.soul > 0]))
            for t in sorted(TreasureObject.every, key=lambda t: t.pointer):
                if t.pointer in done_pointers:
                    continue
                soul_type, soul = souls.pop(0)
                t.item_type = soul_type + 5
                t.item_index = soul
                print "%x" % t.pointer, t.name

            for m in MonsterObject.every:
                m.soul_type = 3
                m.soul = 4

            s = ShopIndexObject.get(0x80)
            s.item_type, s.item_index = 4, 0x13
            s = ShopIndexObject.get(0x81)
            s.item_type, s.item_index = 4, 0x2c
            for i in ItemObject.every:
                i.price = 0

        enable_cutscene_skip()
        clean_and_write(ALL_OBJECTS)
        finish_interface()
    except Exception, e:
        print "ERROR: %s" % e
        raw_input("Press Enter to close this program.")
