from randomtools.tablereader import (
    TableObject, get_global_label, tblpath, addresses)
from randomtools.utils import (
    classproperty, mutate_normal, shuffle_bits, get_snes_palette_transformer,
    write_multi, utilrandom as random)
from randomtools.interface import (
    get_outfile, get_seed, get_flags, run_interface, rewrite_snes_meta,
    clean_and_write, finish_interface)
from collections import defaultdict
from os import path
from time import time
from collections import Counter
import string


VERSION = 1
ALL_OBJECTS = None
DEBUG_MODE = False
RESEED_COUNTER = 0


def reseed():
    global RESEED_COUNTER
    RESEED_COUNTER += 1
    seed = get_seed()
    random.seed(seed + (RESEED_COUNTER**2))


class MonsterObject(TableObject):
    flag = "s"
    flag_description = "enemy souls"
    intershuffle_attributes = [("soul_type", "soul")]


class TreasureObject(TableObject): pass


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

        import pdb; pdb.set_trace()
        clean_and_write(ALL_OBJECTS)
        finish_interface()
    except Exception, e:
        print "ERROR: %s" % e
        raw_input("Press Enter to close this program.")
