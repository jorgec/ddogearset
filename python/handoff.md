# DDO ILP Gearset Optimizer Handoff

## What Was Created
The following files were created to form a complete Integer Linear Programming (ILP) gear optimizer for Dungeons & Dragons Online (DDO):

*   **`optimizer.py`**: The core optimization engine. It parses XML data (Items, Augments, Sets, Filigrees) from DDOBuilderV2, sets up the mathematical model using `pulp`, and runs the solver to find the optimal gear layout.
*   **`cli.py`**: A command-line interface that guides the user through setting up their build. It prompts for build type (Melee, Ranged, Caster), weapon styles, stat priorities, and specific constraints (armor types, minor artifact restrictions, max level caps) and passes these to the optimizer.
*   **`requirements.txt`**: Declares project dependencies (specifically `pulp` for the ILP solver).
*   **Test Output Files** (`test*.txt`, `arti.txt`, `solver_progress.log`, `test.log`): Various text files containing the results of test runs for different scenarios (caster builds, dinosaur bone crafting constraints, multi-level caps).

## How It Was Created
The tool was built in Python using the `pulp` library to treat gear selection as a constrained optimization problem.

1.  **Data Ingestion**: Standard libraries (`xml.etree.ElementTree`, `glob`) are used to read the extensive XML dataset from `DDOBuilderV2/Output/DataFiles`. The parsers (`parse_items`, `parse_sets`, `parse_augments`, `parse_filigrees`) filter out irrelevant gear (e.g., items below ML 29) and map the raw text descriptions of stats into normalized strings matching the user's priorities.
2.  **ILP Modeling**: 
    *   **Variables**: Binary decision variables are created for items in slots, set bonuses, augments, and filigrees.
    *   **Constraints**: The model enforces strict game mechanics. Examples include: exactly one item per equipment slot, maximum of one minor artifact, enforcing two-handed/two-weapon fighting rules, and ensuring augment/filigree selections do not exceed the slots provided by the equipped gear.
    *   **Objective Function**: The engine assigns weights to user priorities (e.g., priority #1 is weighted highest). The objective is to maximize the total weighted sum of stats provided by all active items, sets, augments, and filigrees.
3.  **Solver execution**: The script solves the generated ILP matrix and formats the best configuration into a readable output file.

## Why It Was Created
Endgame gearing in DDO is notoriously complex. With hundreds of items, overlapping set bonuses, customizable augments, and sentient weapon filigrees, finding the mathematical "best" setup manually is practically impossible and extremely time-consuming. 

By formulating gear selection as an Integer Linear Programming problem, this project automates the theorycrafting process. It allows players to simply state what they want (e.g., "Maximize Charisma, Evocation DC, and Spell Penetration") and mathematically proves the absolute best combination of items and sets to achieve that goal, removing guesswork and saving hours of manual spreadsheet planning.
