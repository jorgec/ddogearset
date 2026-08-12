# DDO Gearset Optimizer

A desktop app that solves one question for Dungeons & Dragons Online players:

> Out of every item in the game, which fourteen do I wear?

You say what you want more of. It searches the whole item catalog and returns
the combination that gives you the most of it.

Find this useful? [![PayPal](https://img.shields.io/badge/PayPal-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://www.paypal.com/cgi-bin/webscr?cmd=_donations&business=jorge.cosgayon@gmail.com)

## It doesn't know anything about your build

This is the important part, and it is a deliberate design choice rather than a
missing feature.

The optimizer has no opinion about classes, feats, enhancement trees, or what
"should" go on a Barbarian. It has never heard of your build. What it has is a
list of items, a list of the numbers those items grant, and the stats *you* said
matter — and from those it solves a constrained maximization problem.

That means:

- **You supply the judgment.** Deciding that Melee Power matters more than
  Doublestrike is a D&D question, and it stays yours. The app only answers the
  arithmetic question that follows.
- **It will surprise you.** With no preconceptions to protect, it happily
  proposes an item nobody thinks of as a caster item because the numbers say so.
  Some of those are genuine finds. Some are artifacts of how you weighted things.
  Both are useful information.
- **Garbage in, garbage out.** A vague priority list produces a vague gearset.
  Tell it precisely what you want and it becomes very good.

It is a calculator, not an advisor. That's the whole idea: the math is the part
a computer does better than you, so the app does only that part.

## How it decides

Under the hood this is an **integer linear program**. Every item is a yes/no
variable, the slot rules and your restrictions are constraints, and your stat
priorities become the objective function. A solver then proves which assignment
is best.

"Proves" is meant literally. It isn't sampling promising combinations or
following a greedy heuristic — within the constraints you set, the answer it
returns is optimal, and it knows it. Priorities are ranked in **five tiers**:
everything in Tier 1 is maximized first, and no lower tier is ever allowed to
cost you a point of a higher one.

## What you can do with it

- Solve a full gearset for melee, ranged, caster, or tank builds
- Rank the stats you care about across five priority tiers, or start from a preset
- Pin items, augments, and filigrees you already own and let the solver work around them
- Constrain by weapon style, armor, character level, raid items, and owned expansions
- Import your Trove inventory to restrict the search to gear you actually have
- Compare a proposal against your current gear before accepting any of it
- Save builds to a local database, and export/share them as `.ddogearset` files

**[→ Read the user guide](docs/USAGE.md)**

## Installing

Grab the release for your platform from the
[Releases page](https://github.com/jorgec/ddogearset/releases) — the
[user guide](docs/USAGE.md) covers setup for each. There's nothing to configure
and nothing to download separately: game data ships inside the app, and it never
needs the internet to solve.

## Game data

Item, augment, filigree, and set data comes from
[Maetrim/DDOBuilderV2](https://github.com/Maetrim/DDOBuilderV2). Enormous thanks
to Maetrim and its contributors for maintaining that dataset — this app would not
exist without it.

Data is compiled into the app at build time, so a given release always sees a
fixed, known snapshot of the game rather than whatever a live fetch happened to
return.

DDO Gearset Optimizer is an independent project, not affiliated with DDOBuilderV2
or with Standing Stone Games.

## For developers

Wails v2, Go, Svelte, TypeScript, and a bundled Python/PuLP solver. Building,
refreshing game data, and cutting releases are documented in
[docs/housekeeping.md](docs/housekeeping.md); architecture notes live in
[docs/ENGINEERING.md](docs/ENGINEERING.md).
