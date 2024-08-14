# example usage:
# python3 scripts/update_factorymod.py --server "civclassic 2.0" --factory all
# python3 scripts/update_factorymod.py --server "civclassic 2.0" --factory "Ore Smelter"
# python3 scripts/update_factorymod.py --server "civmc" --factory all --dry

from argparse import ArgumentParser

import yaml

from civwiki_tools.utils import RESOURCES, relog
from civwiki_tools.factorymod import parse_factorymod, RecipeType, Factory, Config
from civwiki_tools import site

config_files = {
    "civcraft 3.0": RESOURCES / "civcraft 3.0.yaml",
    "civclassic 2.0": RESOURCES / "civclassic 2.0.yaml",
    "civmc": RESOURCES / "civmc.yaml"
}
# --server may be passed as e.g. civclassic 2.0, but the template page
# exists at CivClassic 2.0.
wiki_server_names = {
    "civcraft": "Civcraft",
    "civclassic": "CivClassic",
    "civmc": "CivMC"
}

# not sure where some of these servers got some of these names. Did "Oak Log"
# and "Oak Planks" really used to be called "Log" and "Wood"?
item_mappings = {
    # for civcraft 3.0
    # TODO should we move these to redirects wiki-side instead?
    "Log": "Oak Log",
    "Wood": "Oak Planks",
    "Wool": "White Wool",
    "Quartz Ore": "Nether Quartz Ore",
    "Sapling": "Oak Sapling",
}

page_title = "Template:FactoryModConfig_{factory}_({server})"

# sane representation of floats that rounds where appropriate to not show crazy
# decimal places to users.
# TODO this probably rounds to much at the low end, e.g. beacons go from
# 0.0000037037 -> 0.004%. Our worst case should be two decimals *of precision*,
# not any two decimals period.
def float_to_string(val):
    assert round(val, 12) != 0
    v = val
    # take the least precise variant that doesn't round to 0, or show to 2
    # decimal places otherwise.
    # TODO as above, this should be 2 decimal places *of precision* otherwise.
    # might be a bit tricky.
    for i in reversed(range(2, 12)):
        if round(val, i) == 0:
            break
        v = round(val, i)

    return f"{v:.12f}".rstrip("0").rstrip(".")


class FactoryModPrinter:
    def __init__(self, config: Config, factory: Factory):
        self.config = config
        self.factory = factory
        # recipes with randomized outputs. These get their own tables at the end,
        # as their outputs can be quite long.
        self.random_recipes = []
        self.output = ""

    def write(self, text):
        self.output += text

    def get_value(self):
        self.write(self.meta_table())
        self.write("\n\n")
        self.write(self.recipes_table())

        # write any random recipe tables that got added as a result of creating the
        # recipes table
        random_tables = self.random_recipes_tables()
        if random_tables:
            self.write("\n\n")
            self.write(random_tables)

        return self.output

    def image(self, item_name):
        item_name = item_name.replace("_", " ").title()
        if item_name in item_mappings:
            item_name = item_mappings[item_name]
        return f"[[File:{item_name}.png|23px|middle]]"

    def quantity_cell(self, quantities):
        return ", ".join(f"{c.amount} {self.image(c.material)}" for c in quantities)

    def recipe_quantity_cell(self, recipe, type):
        if type == "input":
            if recipe.input:
                return self.quantity_cell(recipe.input)
            else:
                # TODO: "decompact"
                return "TODO"
        if type == "output":
            if recipe.output:
                return self.quantity_cell(recipe.output)
            elif recipe.outputs:
                self.random_recipes.append(recipe)
                # we'll create this anchor when we create the table for this recipe
                # later. As a random recipe, it gets its own table.
                return f"[[#{recipe.name}|{recipe.name}]]"
            else:
                # TODO: "print note" / "compact"
                return "TODO"

    def fuel_cost(self, recipe):
        return recipe.production_time * self.config.default_fuel_consumption_intervall

    def time_cell(self, recipe):
        return recipe.production_time

    def fuel_cell(self, recipe):
        cost = self.fuel_cost(recipe)
        # TODO support displaying multiple default fuels, by cycling through them
        # in a gif. look at how minecraft.wiki does variable recipes
        return f"{cost} {self.image(self.config.default_fuel[0].material)}"

    def repair_recipes(self):
        repair_recipes = [r for r in self.factory.recipes if r.type is RecipeType.REPAIR]

        return "".join(f"""
            |-
            |{self.recipe_quantity_cell(r, "input")}
            |{r.health_gained}
            |{self.time_cell(r)}
            |{self.fuel_cell(r)}""" for r in repair_recipes)

    def recipes(self):
        non_production_types = [RecipeType.UPGRADE, RecipeType.REPAIR]
        recipes = [r for r in self.factory.recipes if r.type not in non_production_types]
        return "".join(f"""
            |-
            |{r.name}
            |{self.recipe_quantity_cell(r, "input")}
            |{self.recipe_quantity_cell(r, "output")}
            |{self.time_cell(r)}
            |{self.fuel_cell(r)}""" for r in recipes)

    def upgrades_from_to(self):
        upgrades_from = self.config.upgrades_from[self.factory.name]
        upgrades_to = self.config.upgrades_to[self.factory.name]

        rows = []

        # number of upgrades to / from recipes might be imbalanced. Pad whichever
        # is lowest with {n/a} rows
        for i in range(max(len(upgrades_from), len(upgrades_to))):
            (r_from, f_from) = upgrades_from[i] if i < len(upgrades_from) else (None, None)
            (r_to, f_to) = upgrades_to[i] if i < len(upgrades_to) else (None, None)
            row = f"""
                |-
                |{f"{f_from.name}\n|{self.recipe_quantity_cell(r_from, "input")}" if f_from else " colspan=\"2\" {{n/a}}"}
                |{f"{f_to.name}\n|{self.recipe_quantity_cell(r_to, "input")}" if f_to else " colspan=\"2\" {{n/a}}"}
            """

            rows.append(row)

        table = """
            |-
            !Upgrades From
            !Cost
            !Upgrades To
            !Cost
        """.strip()
        if not rows:
            table += """
                |-
                | colspan=\"2\" {{n/a}}
                | colspan=\"2\" {{n/a}}"""
        table += "".join(rows)
        return table

    # creation cost and repair recipes
    def meta_table(self):
        return f"""
            {{| class="wikitable"
            |+
            ! colspan="4" |Creation Cost
            |-
            | colspan="4" {f"|{self.quantity_cell(self.factory.setupcost)}" if self.factory.setupcost else "{{n/a}}"}
            |-
            ! colspan="4" |Repair Cost
            |-
            !Cost
            !Health Repaired
            !Time
            !Fuel
            {self.repair_recipes()}
            {self.upgrades_from_to()}
            |}}
        """.strip()

    def recipes_table(self):
        return f"""
            {{| class="wikitable"
            !Recipe
            !Input
            !Output
            !Time
            !Fuel
            {self.recipes()}
            |}}
        """.strip()

    def random_recipe_cells(self, recipe):
        assert recipe.outputs

        return "".join(f"""
            |-
            |{float_to_string(random_output.chance * 100)}%
            |{self.quantity_cell(random_output.quantities)}"""
            for random_output in sorted(recipe.outputs, key=lambda output: -output.chance)
        )

    def random_recipes_tables(self):
        tables = []
        for random_recipe in self.random_recipes:
            tables.append(f"""
            {{| class="wikitable"
            |+{{{{anchor|{random_recipe.name}}}}} {random_recipe.name}
            !Probability
            !Drops
            {self.random_recipe_cells(random_recipe)}
            |}}
        """.strip())

        return "\n\n".join(tables)

def update_factory(config, factory, *, confirm=False, dry=False):
    printer = FactoryModPrinter(config, factory)
    new_text = printer.get_value()

    # --server may be passed as e.g. civclassic 2.0, but the template page
    # exists at CivClassic 2.0.
    wiki_server_name = args.server
    for k, v in wiki_server_names.items():
        wiki_server_name = wiki_server_name.replace(k, v)

    title = page_title.format(factory=factory.name, server=wiki_server_name)
    page = site.page(title)
    title = page.title()

    if page.text == new_text:
        print(f"Nothing has changed for {title}. Skipping update")
        return

    if confirm:
        y_n = input(f"update {title}? y/n ")
        if y_n.lower() != "y":
            print(f"skipped {title}")
            return

    page.text = new_text

    if dry:
        print(page.text)
        return

    while True:
        try:
            page.save()
            return
        except Exception as e:
            print(f"ignoring exception {e}. Relogging...")
            relog()

if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--server", required=True)
    parser.add_argument("--factory", required=True)
    parser.add_argument("--dry", action="store_true", default=False)
    args = parser.parse_args()

    if args.server not in config_files:
        raise ValueError(f"invalid server {args.server}. Expected one of "
            f"{list(config_files.keys())}")

    config_file = config_files[args.server]
    with open(config_file) as f:
        data = yaml.safe_load(f)

    config = parse_factorymod(data)
    if args.factory == "all":
        factories = config.factories
    else:
        factories = [f for f in config.factories if f.name == args.factory]
        if not factories:
            raise ValueError(f"no factory named {args.factory}. Expected one of "
                f"{[f.name for f in config.factories]}")

    for factory in factories:
        update_factory(config, factory, dry=args.dry)
