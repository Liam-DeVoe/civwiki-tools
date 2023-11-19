from enum import Enum
from typing import get_type_hints, get_origin, get_args
from dataclasses import dataclass

def parse_list(ModelClass, data):
    models = []
    for key, value in data.items():
        v = ModelClass.parse(value)
        v.key = key
        models.append(v)
    return models

class Model:
    def __init_subclass__(cls):
        return dataclass(cls)

    @classmethod
    def parse(cls, data):
        type_hints = get_type_hints(cls)
        kwargs = {}
        for attr, type_ in type_hints.items():
            # optional keys. e.g. setupcost is not required for factories
            if attr not in data:
                kwargs[attr] = None
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

class RecipeInputOutput(Model):
    material: str
    amount: int
    lore: list[str]

class Recipe(Model):
    production_time: str
    fuel_consumption_intervall: str
    name: str
    type: RecipeType
    input: list[RecipeInputOutput]
    output: list[RecipeInputOutput]
    health_gained: int
    compact_lore: str
    excluded_materials: list[str]


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
    default_update_time: str
    default_fuel: list[Fuel]
    default_fuel_consumption_intervall: str
    default_return_rate: float
    default_break_grace_period: str
    decay_intervall: str
    decay_amount: int
    default_health: int
    disable_nether: bool
    use_recipe_yamlidentifiers: bool
    log_inventories: bool
    force_include_default: bool

    factories: list[Factory]
    recipes: list[Recipe]


def parse_factorymod(data):
    """
    Parse a .yaml factorymod config.
    """
    config = Config.parse(data)

    # process factory recipe names to actually be the full recipe
    recipes = {r.key: r for r in config.recipes}
    for factory in config.factories:
        factory.recipes = [recipes[name] for name in factory.recipes]

    return config
