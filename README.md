# The MASK

The MASK lets you use an AI tool on a confidential contract without the AI ever reading the
confidential parts. Before you upload a Word or PDF contract, it replaces personal data and
business secrets with placeholders such as `[PERSON_1]` or `[AMOUNT_2]` and keeps the real values
in an encrypted key on your own computer. When the AI gives you back a Word file, it puts the real
values back in. Everything runs on your machine and nothing is ever sent anywhere.

The design is in `docs/superpowers/specs/2026-10-17-the-mask-design.md`. The step-by-step build
plan for the Mac version is in `docs/superpowers/plans/2026-10-17-the-mask-mac-v1.md`.

## Requirements

- macOS (the first version; Windows follows in a later phase)
- [uv](https://docs.astral.sh/uv/). It installs the right Python (3.12) and every pinned
  dependency, including the English language model, for you.

## Run from source

```bash
uv sync
uv run python -m themask
```

`uv sync` needs the network once, to download the dependencies. The finished app never does.

The window opens at once and says "Loading…" for a few seconds while it loads the language model.
A sidebar on the left has three sections: Mask, Restore and Cases. On Mask, drop a Word or PDF
contract on the Mask drop zone (or use "Choose file…", also ⌘O; on Restore, ⌘O chooses the AI's
returned file, and on a review you have not exported it asks before replacing the review) to
analyse it and review what it found. Only that drop zone, and the one on Restore, accept dropped
files; the rest of the window does not.

In the review, a section "Not sure — hide?" lists guesses the analysis was not confident enough
to hide. They stay visible unless you press Hide; Show keeps them visible and stops the question.
Exporting with guesses left unanswered asks first, and the export sheet lists them (and what you
chose to show) separately from anything it finds that you never marked.

You can give a hidden value a name of your own. It is written in the masked copy as `[Name]` in
place of `[PERSON_1]` (double-click the name in the review, or use "Rename mask…"). When names are
used, the instruction for the AI tool changes to say that every name in square brackets is a
placeholder. A name reused across cases may need a manual case pick on restore if the file's name
lost its code (`MASKED-<code>.docx`), because a named file alone does not say which case it is.

The toolbar's "Export…" button saves the masked copy in `~/Documents/The MASK` and keeps its key
in a case on this Mac, locked with a key in your Keychain. Links to web pages and e-mail addresses
are removed from the masked copy; the link text stays. When the AI tool gives you its Word file or
its text back, the Restore section puts the real values back (the toolbar's "Restore" button). It
never guesses which case a file belongs to: it takes the case whose code is in the file's name
(`MASKED-<code>.docx`, which many AI tools keep), and when two cases fit the file equally well it
asks you. A case you chose yourself is never replaced: if another case fits better, the screen
says so. The Cases section lists the saved cases (its toolbar's "New case" button takes you back
to Mask to start one). Settings are in the application menu (The MASK, Settings…, ⌘,) and open in
a window of their own: your always-hide and never-hide lists, how long a case is kept and the
folder of the masked files. They are off while a file is analysed or an export runs.

## Install on your Mac

The MASK is also a normal Mac app, "The MASK.app". It is built for Apple silicon and needs
macOS 26 or newer. It is signed "ad hoc", not by an Apple developer: that is enough to run on the
Mac it was built on, and there is no installer, just the app.

### Build it

You need [uv](https://docs.astral.sh/uv/) and Xcode's command line tools, and the repository must
not be in a folder that iCloud syncs (the Desktop and Documents folders, when iCloud Drive keeps
them): Briefcase stops with an error there. Then, in the repository's root folder:

```bash
bash packaging/build_mac.sh
```

This is the one step that needs the network. Briefcase downloads its Python for macOS and the
pinned packages (the language model too), a few hundred MB that it keeps in a cache, so the next
build is quicker. The packages in the app are the versions in `uv.lock`, the ones the tests run on,
and the build checks that (`tools/check_bundle_lock.py`) before it makes the zip. The build takes a
few minutes, starts from scratch every time, and ends with:

- the app, `build/themask/macos/app/The MASK.app`, about 535 MB;
- a zip of it, `dist/The MASK-0.1.0.app.zip`, about 183 MB.

The app's icon is `packaging/icon/themask.icns`; `uv run python packaging/make_icon.py` draws it
again.

### Install it on this Mac

If an older The MASK.app is already in Applications, quit it and move it to the Trash first.
Copying a new app onto an old one with `ditto` merges the two: files that only the old build had
stay, and the signature no longer fits what is there. (In Finder, Replace is fine.)

Then copy `The MASK.app` to the Applications folder, in Finder or, in Terminal in the repository's
root folder, with

```bash
# Only if an older one is still there:
rm -rf "/Applications/The MASK.app"
ditto "build/themask/macos/app/The MASK.app" "/Applications/The MASK.app"
```

and open it from there. The window opens at once and says "Loading…" while the language model
loads. macOS may ask whether The MASK may use its Keychain item (see below): choose Always Allow.
A rebuilt app is a new program to macOS, so it can ask again.

If the app does not open, or closes at once, start it from Terminal: the errors that Finder hides
are printed there.

```bash
"/Applications/The MASK.app/Contents/MacOS/The MASK"
```

### Open it on another Mac

That Mac needs macOS 26 or newer as well. Copy the zip from `dist/` over (AirDrop, a USB stick),
unzip it and move the app to Applications. macOS refuses to open an app from an unknown developer
the first time. Open System Settings, then Privacy & Security, scroll down to the message that
"The MASK" was blocked and press Open Anyway. (The older way, Control-click and Open, has not
worked since macOS 15, so it does not work on any Mac that can run this app.) It is needed once
for each copy.

### Where it keeps its files

- The data folder, `~/Library/Application Support/The MASK`: the encrypted cases (`cases/`), your
  always-hide and never-hide lists and the settings.
- The log, `~/Library/Application Support/The MASK/logs/themask.log`. It holds counts, types and
  durations, never a word of a contract.
- The masked files, in `~/Documents/The MASK` unless you choose another folder. The first time the
  app writes there, macOS may ask whether it may use your Documents folder: choose Allow.
- The key that locks the cases is not a file. It is an item in the macOS Keychain (service
  "The MASK", account "master-key").

### It never uses the network

The app carries its language model, so it works with Wi-Fi off, and as it starts it shuts the
internet off for itself (`src/themask/netguard.py`): any attempt by the app's own code to open an
internet connection fails. The evidence is what the system sees, not that promise: open the app
and run this in Terminal. It prints nothing when the app has no network connection open:

```bash
lsof -i -a -p $(pgrep -f "The MASK.app")
```

## Develop

```bash
uv run pytest -q              # tests, including the licence gate
uv run ruff check src tests tools packaging   # lint
uv run mypy src               # types (strict)
```

The licence gate (`tests/test_licences.py`) fails if any GPL or AGPL package is installed in the
environment. LGPL libraries (such as Qt for Python) and dual licences with a permissive or LGPL
option are accepted.
