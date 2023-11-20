# example usage:
# python3 scripts/update_factorymod.py --server "civclassic 2.0"

import yaml
from argparse import ArgumentParser
from civwiki_tools.utils import RESOURCES
from civwiki_tools.factorymod import parse_factorymod, RecipeType, Factory, Config

config_files = {
    "civcraft 3.0": RESOURCES / "civcraft 3.0.yaml",
    "civclassic 2.0": RESOURCES / "civclassic 2.0.yaml"
}

def image(item_name):
    item_name = item_name.replace("_", " ").title()
    return f"[[File:{item_name}.png|30px]]"

def quantity_cell(quantities):
    # can happen for random outputs, where output is None but outputs is set
    if quantities is None:
        return "TODO"
    return ", ".join(f"{c.amount} {image(c.material)}" for c in quantities)

def fuel_cost(config, recipe):
    return recipe.production_time * config.default_fuel_consumption_intervall

def time_cell(recipe):
    return recipe.production_time

def fuel_cell(config, recipe):
    cost = fuel_cost(config, recipe)
    # TODO support displaying multiple default fuels, by cycling through them
    # in a gif. look at how minecraft.wiki does variable recipes
    return f"{cost} {image(config.default_fuel[0].material)}"

def repair_recipes(config, factory):
    repair_recipes = [r for r in factory.recipes if r.type is RecipeType.REPAIR]

    return "".join(f"""
        |-
        |{quantity_cell(r.input)}
        |{r.health_gained}
        |{time_cell(r)}
        |{fuel_cell(config, r)}
    """ for r in repair_recipes)

def recipes(config, factory):
    non_production_types = [RecipeType.UPGRADE, RecipeType.REPAIR]
    recipes = [r for r in factory.recipes if r.type not in non_production_types]
    return "".join(f"""
        |-
        |{r.name}
        |{quantity_cell(r.input)}
        |{quantity_cell(r.output)}
        |{time_cell(r)}
        |{fuel_cell(config, r)}
    """ for r in recipes)

def upgrades_from_to(config, factory):
    upgrades_from = config.upgrades_from[factory.name]
    upgrades_to = config.upgrades_to[factory.name]

    rows = []

    # number of upgrades to / from recipes might be imbalanced. Pad whichever
    # is lowest with {n/a} rows
    for i in range(max(len(upgrades_from), len(upgrades_to))):
        (r_from, f_from) = upgrades_from[i] if i < len(upgrades_from) else (None, None)
        (r_to, f_to) = upgrades_to[i] if i < len(upgrades_to) else (None, None)
        # row = f"""
        #     |-
        #     |{f_from.name if f_from else "{{n/a}}"}
        #     |{quantity_cell(r_from.input) if r_from else "{{n/a}}"}
        #     |{f_to.name if f_to else "{{n/a}}"}
        #     |{quantity_cell(r_to.input) if r_to else "{{n/a}}"}
        # """

        row = f"""
            |-
            |{f"{f_from.name}\n|{quantity_cell(r_from.input)}" if f_from else " colspan=\"2\" {{n/a}}"}
            |{f"{f_to.name}\n|{quantity_cell(r_to.input)}" if f_to else " colspan=\"2\" {{n/a}}"}
        """

        rows.append(row)
    return "".join(rows)

# creation cost and repair recipes
def meta_table(config: Config, factory: Factory):
    return f"""
        {{| class="wikitable"
        |+
        ! colspan="4" |Creation Cost
        |-
        | colspan="4" |{quantity_cell(factory.setupcost)}
        |-
        !Upgrades From
        !Cost
        !Upgrades To
        !Cost
        {upgrades_from_to(config, factory)}
        |-
        ! colspan="4" |Repair Cost
        |-
        !Cost
        !Health Repaired
        !Time
        !Fuel
        {repair_recipes(config, factory)}
        |}}
    """

def recipes_table(config: Config, factory: Factory):
    return f"""
        {{| class="wikitable"
        !Recipe
        !Input
        !Output
        !Time
        !Fuel
        {recipes(config, factory)}
        |}}
    """

if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--server", required=True)
    args = parser.parse_args()

    if args.server not in config_files:
        raise ValueError(f"invalid server {args.server}. Expected one of "
            f"{list(config_files.keys())}")

    config_file = config_files[args.server]
    with open(config_file) as f:
        data = yaml.safe_load(f)

    config = parse_factorymod(data)
    factory = config.factories[8]
    print(meta_table(config, factory))
    print(recipes_table(config, factory))


    # page = site.page("Factories (Civcraft 3.0)")
    # page.text = page.text.replace("foo", "bar")
    # print(page.text)
