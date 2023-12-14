from enum import Enum
from typing import get_type_hints, get_origin, get_args
from dataclasses import dataclass
from collections import defaultdict

def parse_list(ModelClass, data):
    models = []
    for key, value in data.items():
        v = ModelClass.parse(value)
        v.key = key
        models.append(v)
    return models

class Model:
    def __init_subclass__(cls):
        return dataclass(cls, kw_only=True)

    @classmethod
    def parse(cls, data):
        type_hints = get_type_hints(cls)
        kwargs = {}
        for attr, type_ in type_hints.items():
            # optional keys. e.g. setupcost is not required for factories
            if attr not in data:
                # default to [] for lists
                default = None if get_origin(type_) is not list else []
                # individual attributes can specify defaults
                default = getattr(cls, attr, default)
                kwargs[attr] = default
                continue

            val = data[attr]

            # uncomment for debugging
            # print(f"processing {attr}: {type_}, value {val}")

            if val is None:
                v = None
            elif get_origin(type_) is list:
                v = val if type(val) is list else parse_list(get_args(type_)[0], val)
            else:
                v = type_(val)

            kwargs[attr] = v
        return cls(**kwargs)

# https://github.com/DevotedMC/CivModCore/blob/ad94009362cfc28d9de4a093d6c966cd0
# 6d09c46/src/main/java/vg/civcraft/mc/civmodcore/util/ConfigParsing.java#L227
class Duration:
    def __init__(self, val):
        # duration in seconds
        seconds = 0
        buffer = ""
        for c in val:
            if c.isdigit():
                buffer += c
                continue
            if c == "s":
                seconds += int(buffer)
            elif c == "m":
                seconds += 60 * int(buffer)
            elif c == "h":
                seconds += 60 * 60 * int(buffer)
            elif c == "d":
                seconds += 24 * 60 * 60 * int(buffer)
            elif c == "t":
                # ticks. used by civcraft, but removed in devoted.
                # https://github.com/Civcraft/CivModCore/blob/70859b8485b39973a
                # bc4aed3a59025a4d1fb8541/src/main/java/vg/civcraft/mc/civmod
                # core/util/ConfigParsing.java#L231

                # 20 ticks per second
                seconds += 0.05 * int(buffer)
            else:
                raise ValueError(f"unimplemented duration identifier {c} "
                    f"(from {val})")
        self.seconds = seconds

    def __int__(self):
        return self.seconds

    def __mul__(self, other):
        if isinstance(other, Duration):
            return self.seconds * other.seconds
        return self.seconds * other

    def __str__(self):
        return str(self.seconds)
    __repr__ = __str__

class RecipeType(Enum):
    UPGRADE = "UPGRADE"
    PRODUCTION = "PRODUCTION"
    REPAIR = "REPAIR"
    COMPACT = "COMPACT"
    DECOMPACT = "DECOMPACT"
    PRINTINGPLATE = "PRINTINGPLATE"
    PRINTINGPLATEJSON = "PRINTINGPLATEJSON"
    WORDBANK = "WORDBANK"
    PRINTBOOK = "PRINTBOOK"
    PRINTNOTE = "PRINTNOTE"
    RANDOM = "RANDOM"

    # used in civcraft 3.0
    WOODMAPPING = "WOODMAPPING"
    PYLON = "PYLON"
    ENCHANT = "ENCHANT"
    LOREENCHANT = "LOREENCHANT"
    COSTRETURN = "COSTRETURN"

class FactoryType(Enum):
    # furnace, chest, crafting table
    FCC = "FCC"
    FCCUPGRADE = "FCCUPGRADE"
    PIPE = "PIPE"
    SORTER = "SORTER"

class Quantity(Model):
    material: str
    amount: int = 1
    lore: list[str]

class RecipeRandomOutput(Model):
    chance: float
    quantities: list[Quantity]

class Recipe(Model):
    production_time: Duration
    fuel_consumption_intervall: Duration
    name: str
    type: RecipeType
    input: list[Quantity]
    output: list[Quantity]
    outputs: list[RecipeRandomOutput]
    health_gained: int
    compact_lore: str
    excluded_materials: list[str]
    # used for RecipeType.UPGRADE recipes
    factory: str


class SetupCost(Model):
    material: str
    amount: int

class Factory(Model):
    type: FactoryType
    name: str
    citadelBreakReduction: float
    setupcost: list[SetupCost]
    recipes: list[str]

class Fuel(Model):
    material: str

class Config(Model):
    default_update_time: Duration
    default_fuel: list[Fuel]
    default_fuel_consumption_intervall: Duration
    default_return_rate: float
    default_break_grace_period: Duration
    decay_intervall: Duration
    decay_amount: int
    default_health: int
    disable_nether: bool
    use_recipe_yamlidentifiers: bool
    log_inventories: bool
    force_include_default: bool

    factories: list[Factory]
    recipes: list[Recipe]

    # set by parse_factorymod.
    # both are a mapping of factory_name to list[(upgrade_recipe, Factory)]
    # upgrades_to: dict[str, list[(recipe, Factory)]]
    # upgrades_from: dict[str, list[(recipe, Factory)]]

def parse_factorymod(data):
    """
    Parse a .yaml factorymod config.
    """
    config = Config.parse(data)

    # process factory recipe names to actually be the full recipe
    recipes = {r.key: r for r in config.recipes}
    for factory in config.factories:
        factory_recipes = factory.recipes
        factory.recipes = []
        for recipe_name in factory_recipes:
            if recipe_name not in recipes:
                print(f"Could not find recipe {recipe_name} (from factory "
                    f"{factory.name}) in list of recipes. Skipping")
                continue
            factory.recipes.append(recipes[recipe_name])

    upgrades_to = defaultdict(list)
    upgrades_from = defaultdict(list)
    for factory in config.factories:
        for recipe in factory.recipes:
            if recipe.type is not RecipeType.UPGRADE:
                continue
            # Upgrade_to_Wood_Processor_2 in civcraft 3.0.yaml doesn't specify
            # a factory: attribute. sigh. how did this get past civmodcore
            # validation?
            if recipe.factory is None:
                continue
            next_factory = [f for f in config.factories if f.name == recipe.factory]
            assert len(next_factory) == 1
            next_factory = next_factory[0]
            upgrades_to[factory.name].append([recipe, next_factory])
            upgrades_from[next_factory.name].append([recipe, factory])

    config.upgrades_to = upgrades_to
    config.upgrades_from = upgrades_from
    return config
