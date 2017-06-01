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


VERSION = 6
ALL_OBJECTS = None
DEBUG_MODE = False
RESEED_COUNTER = 0
ITEM_NAMES = {}
LABEL_PRESET = {}
BESTIARY_DESCRIPTIONS = []
custom_items = {}


HP_HEALING_ITEMS = range(0, 0x05) + range(0x0a, 0x17)


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


def get_text(pointer):
    label = get_global_label()
    f = open(get_outfile(), "r+b")
    f.seek(pointer)
    s = ""
    while True:
        peek = f.read(1)
        if label == "AOS_NA" and ord(peek) == 1:
            break
        elif ord(peek) == 0xF0:
            pointer = f.tell()
            peek2 = f.read(1)
            if ord(peek2) == 0:
                break
            f.seek(pointer)
        s += peek
    if label == "AOS_NA":
        trim = [chr(0), chr(6), chr(0xa)]
    else:
        s = s.lstrip(chr(0))
        trim = [chr(0), chr(0xa)]
    while s[-1] in trim:
        for c in trim:
            s = s.rstrip(c)
    pointer = f.tell()
    f.close()
    return s, pointer


def bytestring_to_sjis(s):
    s = s.lstrip(chr(0))
    #print map(hex, map(ord, s))
    assert len(s) % 2 == 0
    even = [c for (i, c) in enumerate(s) if i % 2 == 0]
    odd = [c for (i, c) in enumerate(s) if i % 2 == 1]
    s = ["".join([a, b]) for (a, b) in zip(odd, even)]
    ss = []
    for c in s:
        try:
            c = c.decode("sjis")
        except UnicodeDecodeError:
            c = "?"
        ss.append(c)
    ss = "".join(ss)
    return ss


class RoutingException(Exception): pass


class MonsterObject(TableObject):
    flag = "d"
    flag_description = "enemy souls and drops"
    intershuffle_attributes = [("soul_type", "soul"),
                               "common_drop",
                               "rare_drop"]

    @property
    def name(self):
        soul_type, soul = self.old_soul
        soul_type = soul_type + 5
        soul = soul
        index = (soul_type << 8) | soul
        try:
            return get_item_names()[index]
        except KeyError:
            return "UNKNOWN MONSTER"

    @property
    def bestiary(self):
        if not BESTIARY_DESCRIPTIONS:
            pointer = addresses.enemy_descriptions
            for m in MonsterObject.every:
                desc, pointer = get_text(pointer)
                BESTIARY_DESCRIPTIONS.append(desc)
        return BESTIARY_DESCRIPTIONS[self.index]

    def restore_soul(self):
        other = [m for m in MonsterObject.every
                 if (m.soul_type, m.soul) == self.old_soul][0]
        self.soul_type, other.soul_type = other.soul_type, self.soul_type
        self.soul, other.soul = other.soul, self.soul
        assert (self.soul_type, self.soul) == self.old_soul

    @property
    def old_soul(self):
        if hasattr(self, "_old_soul"):
            return self._old_soul
        self._old_soul = (self.soul_type, self.soul)
        return self.old_soul

    @property
    def old_soul_type(self):
        return self.old_soul[0]

    @property
    def old_soul_index(self):
        return self.old_soul[1]

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
        item_rando = ("i" in get_flags() or "chaos" in codes
                      or "bat" in codes or "oops" in codes)
        if self.index in [0x5F, 0x68] and not item_rando:
            return False
        return True

    @classmethod
    def intershuffle(cls):
        for m in MonsterObject.every:
            m.name
        monsters = [m for m in MonsterObject.ranked
                    if m.intershuffle_valid]
        max_index = len(monsters)-1
        hard_mode = "chaos" in get_activated_codes()
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
            while True:
                i = ItemObject.superget(value-1)
                i = i.get_similar()
                if ("fam" in get_activated_codes() and i.item_type == 2
                        and i.index in HP_HEALING_ITEMS):
                    continue
                value = (value & 0xFF00) | (i.superindex+1)
                setattr(self, attr, value)
                break

    @property
    def rank(self):
        hard_mode = "chaos" in get_activated_codes()
        if hard_mode:
            if self.xp == 0:
                return 20000 + random.random()
            else:
                return self.xp + random.random()
        else:
            return 0

    def cleanup(self):
        assert 0 <= self.soul_type <= 3


class ItemObject(TableObject):
    @property
    def rank(self):
        if self.price == 0:
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

    @classproperty
    def ranked(self):
        if self is ItemObject:
            return sorted(ItemObject.every,
                          key=lambda i: (i.rank, random.random()))
        return super(ItemObject, self).ranked


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
    def insert_item(cls, item_type, item_index):
        candidates = [s for s in ShopIndexObject.every
                      if hasattr(s, "shop_rank")
                      and s.shop_rank == 3
                      and not s.inserted_item]
        chosen = random.choice(candidates)
        chosen.inserted_item = True
        chosen.item_type = item_type
        chosen.item_index = item_index

    @classmethod
    def randomize_all(cls):
        f = open(get_outfile(), "r+b")
        f.seek(addresses.hammer3)
        num_items = ord(f.read(1))
        indexes = map(ord, f.read(num_items))
        f.close()
        sios = [ShopIndexObject.get(i) for i in indexes]
        hard_mode = "chaos" in get_activated_codes()
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
                if ("fam" in get_activated_codes() and item_type == 2
                        and chosen.index in HP_HEALING_ITEMS):
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
                sio.shop_rank = int(address[-1])
                sio.inserted_item = False
            previous = chosen_sios
        f.close()


def route_items():
    hard_mode = "chaos" in get_activated_codes()
    custom_mode = "custom" in get_activated_codes()
    bat_mode = "bat" in get_activated_codes()
    if hard_mode:
        print "CHAOS MODE ACTIVATED"
        ir = ItemRouter(path.join(tblpath, "hard_requirements.txt"))
    elif custom_mode:
        ir = ItemRouter(path.join(tblpath, "hard_requirements.txt"))
        ir.set_custom_assignments(custom_items)
        hard_mode = True
    elif bat_mode:
        print "BAT MODE ACTIVATED"
        ir = ItemRouter(path.join(tblpath, "bat_requirements.txt"))
    else:
        ir = ItemRouter(path.join(tblpath, "requirements.txt"))

    if hard_mode:
        aggression=4
    else:
        aggression=3

    ir.assign_everything(aggression=aggression)

    souls = [(t.item_type, t.item_index) for t in TreasureObject.every
             if t.item_type >= 5]
    souls += [(0x8, 0x04)]  # kicker skeleton

    # save for later when picking items
    item_types = [t.item_type for t in TreasureObject.every]

    for location, item in sorted(ir.assignments.items()):
        try:
            item = int(item, 0x10)
        except ValueError:
            item = LABEL_PRESET[item]
        item_type = item >> 8
        item_index = item & 0xFF
        if (item_type, item_index) in souls:
            souls.remove((item_type, item_index))

    for item_type, item_index in souls:
        item = "%x" % ((item_type << 8) | item_index)
        if bat_mode or hard_mode:
            continue
        ir.assign_item(item, aggression=aggression)

    done_treasures = set([])
    done_items = set([])
    erased_souls = set([])
    for location, item in sorted(ir.assignments.items()):
        location_type, index = location.split('_')
        index = int(index, 0x10)
        try:
            item = int(item, 0x10)
        except ValueError:
            item = LABEL_PRESET[item]
        item_type = item >> 8
        item_index = item & 0xFF
        if location_type == "item":
            t = TreasureObject.get(index)
            t.item_type = item_type
            t.item_index = item_index
            done_treasures.add(t)
        elif location_type == "enemy":
            if item_type < 5:
                if 'h' in get_flags():
                    ShopIndexObject.insert_item(item_type, item_index)
                else:
                    raise RoutingException
            else:
                if 'd' not in get_flags() and location not in custom_items:
                    raise RoutingException
                m = MonsterObject.get(index)
                erased_souls.add((m.soul_type+5, m.soul))
                m.soul_type = item_type-5
                m.soul = item_index
        done_items.add((item_type, item_index))

    if hard_mode and 'd' in get_flags():
        # kicker skeleton + rush souls
        banned_souls = [(3, 4), (1, 0x12), (1, 0x13), (1, 0x14)]
        for m in MonsterObject.every:
            if (m.soul_type, m.soul) in banned_souls:
                m.soul_type = 0
                m.soul = 1

    if 'd' in get_flags():
        # replace boss souls to prevent softlocks
        winged = [m for m in MonsterObject.every
                  if m.soul_type == 0 and m.soul == 1]
        kicker = [m for m in MonsterObject.every
                  if m.soul_type == 3 and m.soul == 4]
        replaceable = kicker + winged
        headhunter = MonsterObject.get(0x6a)
        legion = MonsterObject.get(0x6c)
        balore = MonsterObject.get(0x6d)
        bosses = [headhunter, legion, balore]

        if hard_mode:
            banned = [(8, 0x05), (6, 0x02)]
        else:
            banned = []

        random.shuffle(bosses)
        for boss in bosses:
            hexdex = "enemy_{0:0>2}".format("%x" % boss.index)
            if hexdex in custom_items:
                continue
            if boss is legion:
                locations = [addresses.legion1, addresses.legion2]
                souls = set([(8, 0x03), (8, 0x05), (6, 0x02)])
            elif boss is balore:
                locations = [addresses.balore1, addresses.balore2,
                             addresses.balore3]
                souls = set([(8, 0x03), (8, 0x05), (6, 0x03), (6, 0x02)])
            elif boss is headhunter:
                locations = [addresses.headhunter1, addresses.headhunter4,
                             addresses.headhunter5]
                souls = set([(6, 0x02), (6, 0x03), (7, 0x01),
                             (8, 0x02), (8, 0x04), (8, 0x05)])
            else:
                raise Exception
            locations = set([
                (t.get_by_pointer(l).item_type, t.get_by_pointer(l).item_index)
                for l in locations])
            if locations & souls:
                continue
            soulstrs = dict([((a, b), "{0}{1:0>2}".format("%x" % a, "%x" % b))
                             for (a, b) in souls])
            order = ['a', 'b']
            random.shuffle(order)
            for o in order:
                if o == 'a':
                    temp = [s for s in souls
                            if ir.get_item_rank(soulstrs[s]) is not None]
                    if temp:
                        souls = temp
                if o == 'b':
                    temp = [s for s in souls if s not in banned]
                    if temp:
                        souls = temp
            souls = sorted(
                souls, key=lambda s: (ir.get_item_rank(soulstrs[s]),
                                      random.random()))
            soul_type, soul = souls.pop(0)
            soul_type -= 5
            if replaceable:
                replacement = replaceable.pop(0)
                replacement.soul_type = boss.soul_type
                replacement.soul = boss.soul
            else:
                erased_souls.add((boss.soul_type+5, boss.soul))
            boss.soul_type = soul_type
            boss.soul = soul
            assert 0 <= boss.soul_type <= 3

    remaining_treasures = [t for t in TreasureObject.every
                           if t not in done_treasures]
    random.shuffle(remaining_treasures)
    max_rank = max(ir.location_ranks)
    oops_all_souls = 'oops' in get_activated_codes()
    if oops_all_souls:
        print "OOPS ALL SOULS MODE ACTIVATED"
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
            index = ItemObject.ranked.index(old_item)
            old_ratio = index / float(len(ItemObject.every))
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
                item_index = random.randint(0, max_index)
                if item_index >= 4:
                    item_index = random.randint(4, item_index)
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
                souls = None
                if erased_souls:
                    souls = sorted(erased_souls)
                    souls = [s for s in souls if s not in done_items]
                if not souls:
                    souls = [(m.soul_type+5, m.soul)
                             for m in MonsterObject.every
                             if m.soul > 0 or m.soul_type > 0]
                    souls = [s for s in souls if s not in done_items]
                if not souls:
                    item_type = 1
                    item_index = 6
                else:
                    item_type, item_index = random.choice(souls)
            if ((item_type >= 3 or
                    (item_type == 1 and item_index <= 3) or
                    (item_type == 2 and item_index >= 0x19)) and
                    (item_type, item_index) in done_items):
                continue
            if hard_mode and (item_type, item_index) in [
                    (6, 0x12), (6, 0x13), (6, 0x14), (8, 0x04)]:
                continue
            if ("fam" in get_activated_codes() and item_type == 2
                    and item_index in HP_HEALING_ITEMS):
                continue
            t.item_type = item_type
            t.item_index = item_index
            done_items.add((item_type, item_index))
            break

    if 'safe' not in get_activated_codes():
        for t in TreasureObject.every:
            if (t.item_type == 1 and t.item_index >= 4
                    and random.randint(1, 5) == 5):
                t.difficulty = 1
                t.item_type = 0x60
                t.memory_flag = 1
                t.item_index = random.randint(0, 2)
    else:
        print "SAFE TREASURE MODE ACTIVATED"


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
    s = ("%s-%s" % (VERSION, get_seed())) + chr(0x06)
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
            'chaos': ['chaos', 'hard'],
            'fam': ['famine'],
            'safe': ['goodmoney', 'good money', 'good_money'],
            'custom': ['custom'],
        }
        run_interface(ALL_OBJECTS, snes=True, codes=codes)

        activated_codes = get_activated_codes()
        if "custom" in activated_codes:
            print "CUSTOM MODE ACTIVATED"
            custom_filename = raw_input("Filename for custom items seed? ")
            f = open(custom_filename)
            for line in f:
                if '#' in line:
                    index = line.index('#')
                    line = line[:index]
                line = line.strip()
                while '  ' in line:
                    line = line.replace('  ', ' ')
                line = line.strip()
                line = line.split()
                if len(line) == 2:
                    location, item = line
                    location = location.split('_')
                    assert len(location) >= 2
                    location = location[0] + "_" + location[-1]
                    custom_items[location] = item

        if "fam" in activated_codes:
            print "FAMINE MODE ACTIVATED"

        '''
        for m in MonsterObject.every:
            if get_global_label() != "AOS_NA":
                print "%x" % m.index, bytestring_to_sjis(m.bestiary)
            else:
                print "%x" % m.index, m.bestiary
        '''

        route_item_flag = ('i' in get_flags() or "oops" in activated_codes
                           or "bat" in activated_codes
                           or "custom" in activated_codes)
        keys = {
            0: "bullet",
            1: "guardian",
            2: "enchanted",
        }
        for i in xrange(3):
            monsters = [m for m in MonsterObject.every
                        if m.old_soul_type == i
                        and (m.old_soul_type > 0 or m.old_soul_index > 0)]
            if not route_item_flag:
                monsters = [m for m in monsters
                            if m.index not in [0x5a, 0x66, 0x69]]
            m = random.choice(monsters)
            if not route_item_flag:
                m.restore_soul()
            soul_type, soul = m.old_soul
            soul_type += 5
            bestiary = m.bestiary
            bestiary = bestiary.strip()
            bestiary = bestiary.rstrip(chr(6))
            key = keys[i]
            LABEL_PRESET["dracula_%s" % key] = (soul_type << 8) | soul
            ancient_addr = getattr(addresses, "ancient_%s" % key)
            ancient, _ = get_text(ancient_addr)
            if get_global_label() == "AOS_NA":
                if len(bestiary) > len(ancient):
                    bestiary = bestiary[:len(ancient)-3]
                    bestiary += "..."
                while len(bestiary) < len(ancient):
                    bestiary += " "
            else:
                if len(bestiary) > len(ancient):
                    bestiary = bestiary[:len(ancient)]
                while len(bestiary) < (len(ancient)/2)*2:
                    bestiary += chr(0x40) + chr(0x81)
                if len(bestiary) < len(ancient):
                    assert False
            f = open(get_outfile(), "r+b")
            f.seek(ancient_addr)
            f.write(bestiary)
            dracula_addr = getattr(addresses, "dracula_%s" % key)
            f.seek(dracula_addr)
            f.write(chr(soul))
            f.close()

        if route_item_flag:
            while True:
                try:
                    route_items()
                except RoutingException:
                    continue
                break

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
