# DDO Gearset Optimizer

DDO Gearset Optimizer is a desktop application for creating Dungeons & Dragons
Online gearsets. It uses an integer linear programming solver to select items
that best match a character's build, equipment restrictions, and weighted stat
priorities. Purely a math exercise - this app does not know or care about your build, you have to make the decisions about what's important to you.

The application provides:

- Automatic gearset optimization for melee, ranged, caster, and tank builds.
- Constraints for weapon style, armor, raid items, expansion ownership, minor
  artifacts, and the Gem of Many Facets.
- Manual item, augment, and sentient filigree selections.
- Gearset summaries with active set bonuses and realized stats.
- Save and load support for `.ddogearset` files.

For a walkthrough of the application, see the [user guide](docs/USAGE.md).

Find this useful? [![PayPal](https://img.shields.io/badge/PayPal-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://www.paypal.com/cgi-bin/webscr?cmd=_donations&business=jorge.cosgayon@gmail.com)

## DDOBuilderV2 data

This project uses item, augment, filigree, and related game data from
[Maetrim/DDOBuilderV2](https://github.com/Maetrim/DDOBuilderV2). The upstream
repository is included as the `data/ddobuilder` Git submodule and is an
essential input to the optimizer. Thank you to Maetrim and the DDOBuilderV2
contributors for maintaining this data.

DDO Gearset Optimizer is an independent project and is not affiliated with
DDOBuilderV2.

## Installation

### Current distribution status

There are currently no versioned end-user installers or archives published in
this repository's GitHub Releases. The files under `build/` are build
configuration and local build output, not downloads for end users.

The current bundled solver is a macOS Apple Silicon binary. Windows and Linux
build configuration exists, but those platforms require a matching native
solver binary before an optimizer build can be distributed. Do not download or
run executable files from the source tree as an installation method.

When signed release assets are published, download them only from the
[Releases page](https://github.com/jorgec/ddogearset/releases) and follow the
instructions for your platform below.

### macOS (Apple Silicon)

1. Download the macOS `.zip` release asset and double-click it to extract the
   application.
2. Drag **DDO Gearset Optimizer.app** to **Applications**.
3. Open it from **Applications**. If macOS displays an unidentified-developer
   warning, Control-click the application, choose **Open**, then choose
   **Open** again.

### Windows (64-bit)

1. Download the Windows `-installer.exe` release asset.
2. Double-click the installer and accept the installation location, or choose
   another folder.
3. Start **DDO Gearset Optimizer** from the Start menu or desktop shortcut.

If Windows asks to install the Microsoft Edge WebView2 Runtime, allow the
installer to do so; Wails uses it to display the application interface.

### Linux (64-bit)

1. Download the Linux release archive and extract it with your desktop archive
   manager.
2. Open the extracted folder and run the `DDOGearsetOptimizer` executable.
3. If your file manager does not allow launching it, open the file properties
   and enable **Allow executing file as program**, then launch it again.

Linux desktop environments need the WebKitGTK runtime. A future Linux release
will list the exact distribution packages alongside its download.

## Development

The application is built with Wails v2, Go, Svelte, TypeScript, and a bundled
Python/PuLP solver. Development, data-refresh, and release-build details are
documented in [docs/ENGINEERING.md](docs/ENGINEERING.md).
