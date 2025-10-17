from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import get_args, get_origin, get_type_hints


def parse_list(ModelClass, data):
    models = []
    for key, value in data.items():
        v = ModelClass.parse(value)
        v.key = key
        models.append(v)
    return models


# fields with a value of SPECIAL_PARSING will be parsed in a particular
# hardcoded way that is not worth generalizing or making abstract.
# yes, this is a hack. no, I'm not sorry.
SPECIAL_PARSING_1 = object()
field_name_overrides = {"custom_key": "custom-key"}


class Model:
    def __init_subclass__(cls):
        return dataclass(cls, kw_only=True)

    @classmethod
    def parse(cls, data):
        type_hints = get_type_hints(cls)
        kwargs = {}
        for attr, type_ in type_hints.items():
            if getattr(cls, attr, None) is SPECIAL_PARSING_1:
                val = data.copy()
                del val["chance"]
                kwargs[attr] = parse_list(get_args(type_)[0], val)
                continue

            # yaml sometimes has invalid python identifiers, like custom-key.
            # override our lookup names for those
            yaml_key = field_name_overrides.get(attr, attr)

            # optional keys. e.g. setupcost is not required for factories
            if yaml_key not in data:
                # default to [] for lists
                default = None if get_origin(type_) is not list else []
                # individual attributes can specify defaults
                default = getattr(cls, attr, default)
                kwargs[attr] = default
                continue

            val = data[yaml_key]

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
                raise ValueError(
                    f"unimplemented duration identifier {c} " f"(from {val})"
                )
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

    # used by civmc
    HELIODOR_CREATE = "HELIODOR_CREATE"
    HELIODOR_FINISH = "HELIODOR_FINISH"
    HELIODOR_REFILL = "HELIODOR_REFILL"


class FactoryType(Enum):
    # furnace, chest, crafting table
    FCC = "FCC"
    FCCUPGRADE = "FCCUPGRADE"
    PIPE = "PIPE"
    SORTER = "SORTER"


class Enchantment(Model):
    enchant: str
    level: int


class Quantity(Model):
    material: str
    # amount defaults to 1. At least for civcraft; I haven't checked devoted.
    # https://github.com/Civcraft/CivModCore/blob/70859b8485b39973abc4aed3a59025
    # a4d1fb8541/src/main/java/vg/civcraft/mc/civmodcore/util/ConfigParsing.java
    # #L194
    amount: int = 1
    lore: list[str]

    type: str  # replaces 'material' in civmc config
    custom_key: str  # for custom items

    enchantments: list[Enchantment]

    @classmethod
    def parse(cls, data):
        quantity = super().parse(data)

        enchantments = []
        if "stored_enchants" in data:
            # civclassic/civcraft: stored_enchants dict of {key: {enchant: name, level: num}}
            enchantments = [
                Enchantment.parse(enchant_data)
                for enchant_data in data["stored_enchants"].values()
            ]
        elif "meta" in data and "stored-enchants" in data["meta"]:
            # civmc: meta.stored-enchants dict of {enchant_name: level}
            enchantments = [
                Enchantment(enchant=name, level=level)
                for name, level in data["meta"]["stored-enchants"].items()
            ]

        quantity.enchantments = enchantments
        return quantity


class RecipeRandomOutput(Model):
    chance: float
    # this isn't actually represented as a list in the yaml, and we don't
    # know ahead of time what the key will be (because it's the same as the
    # recipe name, which could be anything like dragon_egg). use a custom parser
    # for it.
    quantities: list[Quantity] = SPECIAL_PARSING_1


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

    # in civmc config, items look like:
    #
    #   charcoal:
    #       v: 3839
    #       ==: org.bukkit.inventory.ItemStack
    #       type: CHARCOAL
    #
    # in civclassic/civcraft, they look like:
    #
    #   charcoal:
    #       material: CHARCOAL
    type: str  # optional, replaces 'material' in civmc
    custom_key: str  # optional, eg civmc heliodor


class Factory(Model):
    type: FactoryType
    name: str
    citadelBreakReduction: float
    setupcost: list[SetupCost]
    recipes: list[str]


class Fuel(Model):
    material: str
    type: str  # optional, replaces 'material' in civmc


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
                print(
                    f"Could not find recipe {recipe_name} (from factory "
                    f"{factory.name}) in list of recipes. Skipping"
                )
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
