"""Print a world grown by the real curator, for judging its quality by eye.

    uv run python -m aigm.world.sample [--passes 2] [--setting "..."]

Seeds a small world (a region, a town, an inn and its barmaid), then runs expansion passes with the
configured models (needs ANTHROPIC_API_KEY; costs a little) and prints every entity with its facts."""

import argparse
import asyncio

from aigm.config import Settings
from aigm.prompts import PromptLibrary
from aigm.world import World
from aigm.world.anthropic_curator import AnthropicCurator
from aigm.world.ops import apply_ops
from aigm.world.passes import PassConfig, run_pass

SETTING = (
    "The Test Marches: a gritty border region of crumbling forts and muddy roads, where the old kingdom's "
    "garrisons have been left to rot. Rival bandit chiefs and a failing baron squabble over toll roads, and "
    "something stirs in the drowned crypts beneath the oldest fort. Grim but not hopeless; low level."
)


def seed() -> World:
    world = World()
    region = world.add_entity("The Marches", "location")
    town = world.add_entity("Dunmere", "location", parent=region.id)
    inn = world.add_entity("The Rusty Flagon", "location", parent=town.id)
    wren = world.add_entity("Wren", "npc")
    world.add_fact("Dunmere is a river town on the old toll road.", [town.id, region.id], aspect="layout")
    world.add_fact("Wren runs the common room of the Rusty Flagon.", [wren.id, inn.id], aspect="role")
    world.set_scene(inn.id, [wren.id])
    return world


def render(world: World) -> str:
    lines = []
    for ent in world.entities.values():
        chain = " > ".join(p.name for p in reversed(world.parent_chain(ent.id)))
        lines.append(f"\n{ent.name} ({ent.kind}{'; in ' + chain if chain else ''})")
        lines += [f"  [{f.aspect or '-'}] {f.text}" for f in world.facts_about(ent.id) if f.subject == ent.id]
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--passes", type=int, default=2)
    parser.add_argument("--setting", default=SETTING)
    args = parser.parse_args()
    settings = Settings()
    curator = AnthropicCurator(
        api_key=settings.anthropic_api_key,
        prompts=PromptLibrary(settings.prompt_dir),
        model=settings.world_model,
        expand_model=settings.world_expand_model,
        effort=settings.world_effort,
        expand_effort=settings.world_expand_effort,
    )
    world = seed()
    for n in range(1, args.passes + 1):
        result = await run_pass(world, [], curator, setting=args.setting, config=PassConfig())
        apply_ops(world, result.ops)
        print(f"pass {n}: {len(result.ops)} ops; " + "; ".join(result.notes))
    print(render(world))


if __name__ == "__main__":
    asyncio.run(main())
