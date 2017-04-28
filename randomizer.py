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
    def name(self):
        soul_type = self.soul_type + 5
        soul = self.soul
        index = (soul_type << 8) | soul
        try:
            return get_item_names()[index]
        except KeyError:
            return "UNKNOWN MONSTER"

    @property
    def pretty_drops(self):
        pretty_drops = []
        for attr in ["common_drop", "rare_drop"]:
            value = getattr(self, attr)
            if value == 0:
                pretty_drops.append("Nothing")
                continue
            pretty_drops.append(ItemObject.superget(value-1).name)
        return ", ".join(pretty_drops)

    @property
    def intershuffle_valid(self):
        if self.soul_type == 0 and self.soul == 0:
            return False
        codes = get_activated_codes()
        item_rando = ("i" in get_flags() or "hard" in codes
                      or "bat" in codes or "oops" in codes)
        if self.index in [0x5F, 0x68] and not item_rando:
            return False
        return True

    @classmethod
    def intershuffle(cls):
        monsters = [m for m in MonsterObject.ranked
                    if m.intershuffle_valid]
        max_index = len(monsters)-1
        hard_mode = "hard" in get_activated_codes()
        if hard_mode:
            def shuffle_func(m):
                index = monsters.index(m)
                rand_index = random.random() * max_index
                ratio = (
                    random.random() + random.random() + random.random()) / 3
                new_index = (index * ratio) + (rand_index * (1-ratio))
                return (new_index, m.index)
        else:
            shuffle_func = lambda m: (random.random(), m.index)

        for attrs in ["common_drop", "rare_drop", ("soul_type", "soul")]:
            if isinstance(attrs, basestring):
                attrs = [attrs]
            shuffled = sorted(monsters, key=shuffle_func)
            for attr in attrs:
                values = [getattr(m, attr) for m in shuffled]
                assert len(values) == len(monsters)
                for m, value in zip(monsters, values):
                    setattr(m, attr, value)

    def mutate(self):
        for attr in ["common_drop", "rare_drop"]:
            value = getattr(self, attr)
            if value == 0:
                continue
            i = ItemObject.superget(value-1)
            i = i.get_similar()
            value = (value & 0xFF00) | (i.superindex+1)
            setattr(self, attr, value)

    @property
    def rank(self):
        hard_mode = "hard" in get_activated_codes()
        if hard_mode:
            if self.xp == 0:
                return 20000 + random.random()
            else:
                return self.xp + random.random()
        else:
            return 0


class ItemObject(TableObject):
    @property
    def rank(self):
        if self.price == 0 and self.item_type >= 3:
            rank = 1000000
        else:
            rank = self.price
        return rank + random.random()

    @property
    def item_type(self):
        if isinstance(self, ConsumableObject):
            item_type = 2
        if isinstance(self, WeaponObject):
            item_type = 3
        elif isinstance(self, ArmorObject):
            item_type = 4
        return item_type

    @property
    def name(self):
        index = self.index
        index |= (self.item_type << 8)
        return get_item_names()[index]

    @classmethod
    def superget(cls, index1, index2=None):
        if index2 is None:
            return (ConsumableObject.every +
                    WeaponObject.every +
                    ArmorObject.every)[index1]
        subcls = {
            2: ConsumableObject,
            3: WeaponObject,
            4: ArmorObject,
        }[index1]
        return subcls.get(index2)

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


class ShopIndexObject(TableObject):
    flag = "h"
    flag_description = "Hammer's shop"

    def __repr__(self):
        return self.item.__repr__()

    @property
    def item(self):
        return ItemObject.superget(self.item_type, self.item_index)

    @classmethod
    def randomize_all(cls):
        f = open(get_outfile(), "r+b")
        f.seek(addresses.hammer3)
        num_items = ord(f.read(1))
        indexes = map(ord, f.read(num_items))
        f.close()
        sios = [ShopIndexObject.get(i) for i in indexes]
        hard_mode = "hard" in get_activated_codes()
        total_new_items = []
        for item_type in [2, 3, 4]:
            subsios = [sio for sio in sios if sio.item_type == item_type]
            new_items = []
            candidates = [i for i in ItemObject.every
                          if i.item_type == item_type and i.price > 0]
            candidates = sorted(candidates,
                                key=lambda c: (c.price, random.random()))
            max_index = len(candidates)-1
            while len(new_items) < len(subsios):
                if hard_mode:
                    index = random.randint(0, random.randint(0, max_index))
                else:
                    index = random.randint(0, max_index)
                chosen = candidates[index]
                if chosen in new_items:
                    continue
                new_items.append(chosen)
            new_items = sorted(new_items, key=lambda ni: ni.index)
            total_new_items.extend(new_items)

        sios = [ShopIndexObject.get(i) for i in xrange(len(total_new_items))]
        for sio, ni in zip(sios, total_new_items):
            sio.item_type = ni.item_type
            sio.item_index = ni.index

        f = open(get_outfile(), "r+b")
        previous = list(sios)
        for address in ["hammer3", "hammer2", "hammer1"]:
            f.seek(getattr(addresses, address))
            num_items = ord(f.read(1))
            f.seek(getattr(addresses, address)+1)
            chosen_sios = random.sample(previous, num_items)
            chosen_sios = sorted(chosen_sios, key=lambda sio: sio.index)
            for sio in chosen_sios:
                f.write(chr(sio.index))
            previous = chosen_sios
        f.close()


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

    for location, item in sorted(ir.assignments.items()):
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
    for location, item in sorted(ir.assignments.items()):
        _, index = location.split('_')
        index = int(index, 0x10)
        item = int(item, 0x10)
        item_type = item >> 8
        item_index = item & 0xFF
        t = TreasureObject.get(index)
        t.item_type = item_type
        t.item_index = item_index
        done_treasures.add(t)
        done_items.add((item_type, item_index))

    remaining_treasures = [t for t in TreasureObject.every
                           if t not in done_treasures]
    random.shuffle(remaining_treasures)
    max_rank = max(ir.location_ranks)
    oops_all_souls = 'oops' in get_activated_codes()
    if oops_all_souls:
        print "OOPS ALL SOULS CODE ACTIVATED"
    for t in remaining_treasures:
        rank = ir.get_location_rank("item_{0:0>2}".format("%x" % t.index))
        if rank is None:
            rank = ((random.random() + random.random() + random.random())
                    * max_rank / 3.0)
        ratio = float(rank) / max_rank
        old_item_type, old_index = t.item_type, t.item_index
        old_ratio = None
        if old_item_type == 1:
            old_ratio = old_index / 6.0
        elif 2 <= old_item_type <= 4:
            old_item = ItemObject.superget(old_item_type, old_index)
            index = old_item.ranked.index(old_item)
            old_ratio = index / float(len(old_item.every))
        if old_ratio is not None and old_ratio > ratio:
            adjustment = ((random.random() + random.random() + random.random())
                          / 3.0)
            ratio = (ratio * adjustment) + (old_ratio * (1-adjustment))

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
                souls = [(m.soul_type+5, m.soul) for m in MonsterObject.every
                         if m.soul > 0 or m.soul_type > 0]
                souls = [s for s in souls if s not in done_items]
                if not souls:
                    item_type = 1
                    item_index = 6
                else:
                    item_type, item_index = random.choice(souls)
            if ((item_type >= 3 or
                    item_type == 1 or
                    (item_type == 2 and item_index >= 0x1a)) and
                    (item_type, item_index) in done_items):
                continue
            if hard_mode and (item_type, item_index) in [
                    (6, 0x12), (6, 0x13), (6, 0x14),
                    (5, 0x2c), (7, 0x07), (8, 0x04),
                    ]:
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
            locations = [addresses.legion1, addresses.legion2]
            souls = set([(8, 0x03), (8, 0x05), (6, 0x02)])
        elif boss is balore:
            locations = [addresses.balore1, addresses.balore2,
                         addresses.balore3]
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
        soul_type -= 5
        replacement = replaceable.pop(0)
        replacement.soul_type = boss.soul_type
        replacement.soul = boss.soul
        boss.soul_type = soul_type
        boss.soul = soul
        assert 0 <= boss.soul_type <= 3


def enable_cutscene_skip():
    # 0x1AF8 is the byte in SRAM that saves whether the game has been beaten
    # (#03 if so) and therefore cutscenes can be skipped.
    # This byte is copied to 02000060 when the game is turned on.
    # When Start is pressed during a cutscene, the byte is loaded from
    # memory at 0x5B56C.
    # This patch changes it to a simple MOV r0, #03 instruction.
    f = open(get_outfile(), "r+b")
    f.seek(addresses.cutscene_skip)
    f.write("".join(map(chr, [0x03, 0x20])))
    f.close()


def write_seed_display():
    f = open(get_outfile(), "r+b")
    f.seek(addresses.start_game_text)
    s = "%s" % get_seed()
    while len(s) < 11:
        s += " "
    s = s[:11]
    f.write(s)
    f.seek(addresses.soul_set_text)
    s = "%s" % get_seed() + chr(0x06)
    s += get_flags() + " " + " ".join(get_activated_codes())
    while len(s) < 26:
        s += " "
    s = s[:26].upper()
    f.write(s)
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
            'oops': ['oopsallsouls', 'oops all souls', 'oops_all_souls'],
            'bat': ['batcompany', 'bat_company', 'bat company'],
            'hard': 'hard',
        }
        run_interface(ALL_OBJECTS, snes=True, codes=codes)

        activated_codes = get_activated_codes()
        if ('i' in get_flags() or "oops" in activated_codes
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

            s = ShopIndexObject.get(0x80)
            s.item_type, s.item_index = 4, 0x13
            s = ShopIndexObject.get(0x81)
            s.item_type, s.item_index = 4, 0x2c
            for i in ItemObject.every:
                i.price = 0

        enable_cutscene_skip()
        if get_global_label() == "AOS_NA":
            write_seed_display()
        clean_and_write(ALL_OBJECTS)
        finish_interface()
    except Exception, e:
        print "ERROR: %s" % e
        raw_input("Press Enter to close this program.")
