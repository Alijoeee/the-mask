# The MASK — every controller ruling of the Mac phase, in plain language

Final (session 3, 19 October 2026, mac-v1 at 4bbde49). Each line: what was decided, and what it costs
if the decision turns out wrong. The design document stays the binding authority; a ruling only settles
a point the plan left open or got wrong. The full reasoning behind each ruling, with the evidence, is in
`notes/sdd/progress.md` (the ledger), by number; the final review and its re-review are in
`notes/sdd/final-review.md`.

## Where things stand
- Branch `mac-v1` at **4bbde49**, pushed: all 25 build tasks merged; the final whole-branch review done
  and its 20-item fix wave merged after one scoped re-review (approved, nothing above Minor left).
- The suite: 3,343 tests green (slow ones included), ruff and mypy clean. Pass marks (design §9): 100 %
  of pattern-type values (913/913) and of names (320/320) found before review, 0 never-hide terms hidden,
  the slowest thirty-page file well under 60 s, the corpus round trip 28/28 files restored exactly.
- Not done, by your instruction: merging `mac-v1` into `main`. Yours: the Mac build, the Wi-Fi-off smoke
  test and Task 26 (sections below). The checkpoint branches `task-22`, `task-24`, `task-25` on GitHub
  are merged and can be deleted.

## The rulings

- **R1** — The whole Mac phase is built on the branch `mac-v1` of the new repository; `main` keeps only the documents until you decide to merge. — *Cost if wrong:* none beyond a branch rename.
- **R2** — A Word file is first copied, its tracked changes accepted (or rejected, for the "before" copy of a redline), then cleaned; the text you review comes from that prepared copy and the export masks that same copy, so every position lines up. — *Cost if wrong:* hidden text is never shown in the review (it is removed anyway) and "[image removed]" notes appear in the review text; both acceptable.
- **R3** — The export's re-scan of a masked file receives the key entries so it can look for exactly the marked values. — *Cost if wrong:* one extra parameter.
- **R4** — The licence gate accepts the Artistic-2.0 licence (needed by one build-time tool, text-unidecode); any GPL/AGPL still fails the gate. — *Cost if wrong:* an Artistic-licensed runtime package could slip in; none is planned.
- **R5** — In the made-up test corpus, amounts in pricing tables carry a currency; only a few deliberately bare numbers appear in prose, so the ≥ 99 % pass mark measures the recognisers, not table-header guessing. — *Cost if wrong:* the corpus is easier than some real tables; the bare-number recogniser still exists and has its own tests.
- **R6** — The licence gate was hardened beyond the plan's verbatim code (real OR/AND handling, word-boundary matching, GPL/Affero wording caught, a self-test). — *Cost if wrong:* about twenty lines; a legitimately dual-licensed developer tool might one day need an allow-list entry.
- **R7** — Independent tasks ran in parallel, each implementer in its own worktree; the controller merged clean branches and ran the whole suite after every merge. — *Cost if wrong:* a merge conflict costs one fixer dispatch; nothing is lost.
- **R8** — Placeholder grammar: a placeholder written without brackets must use `_`, `-` or `\_` as its separator (so "PERSON_1" and "person-1" count as altered placeholders, but plain prose like "Company 1" does not). — *Cost if wrong:* an AI that writes "PERSON 1" without brackets is not caught; the value is still visible to you in the restored text.
- **R9** — Bank details get spelling variants (IBAN without spaces and in groups of four; identifiers without spaces, dots or hyphens) so re-spaced copies are found. — *Cost if wrong:* a few extra variants per bank detail.
- **R10** — Case files have no readable header; listing cases decrypts each file. — *Cost if wrong:* listing many cases costs one decryption each; negligible.
- **R11** — Value patterns refuse to match inside a longer number ("EUR 5" never matches inside "EUR 5,000.00"). — *Cost if wrong:* a value written with a trailing decimal elsewhere is missed by the sweep; the leak check still catches it.
- **R12** — Presidio's IP-address, US driver-licence, US bank-number and medical-licence recognisers are switched off (clause numbers like 12.3.4.1 and product codes were being hidden). — *Cost if wrong:* a literal IP address or US licence number is not hidden automatically; you can hide it by hand.
- **R13** — Four reviewer "minors" that touched visibility or speed were fixed at once in Task 6 instead of being deferred. — *Cost if wrong:* one slightly longer fix round.
- **R14** — The leak check scans every text-bearing part (including attribute values, field instructions and link targets) for every value and variant; numbers only on digit boundaries; raw bytes of non-XML parts only for values of six or more non-digit characters; values shorter than four characters are reported as "not checkable". — *Cost if wrong:* a one-to-three-character secret (such as "3%") that survived masking is not caught by the leak check; the review and the re-scan still show it.
- **R15** — Two reviewer minors (a validity test for IBAN/BIC/VAT/phone values; lazy import of the corpus generator) joined Task 4's fix round. — *Cost if wrong:* a slightly longer round.
- **R16** — Text boxes are stored twice in a Word file; the reader reads the modern copy and the cleaner deletes the legacy fallback copy, so no unmasked second copy can survive. — *Cost if wrong:* Word 2007 would show nothing for those shapes; out of scope.
- **R17** — Equations and embedded foreign content (altChunk) are removed and replaced by a note, because the reader cannot read them and anything unread could leak. — *Cost if wrong:* an equation or embedded HTML block is missing from the masked copy; the AI rarely needs either.
- **R18** — Headers, footers, footnotes and endnotes are found by content type (and by relationship, R20), in a fixed order; table-cell revisions count as tracked changes. — *Cost if wrong:* none.
- **R19** — The cleaner clears every attribute that can carry visible text (watermarks, smart tags, list items, form-field data, tooltips, alt text, table captions, content-control aliases/tags), and the leak check scans attribute values too. — *Cost if wrong:* alt text and tooltips disappear from masked copies; acceptable.
- **R20** — Word parts with a DOCTYPE are refused; XML comments and processing instructions are stripped before reading; header/footer parts are also found through relationships. — *Cost if wrong:* none.
- **R21** — A place name the model reports is kept as a person or company when it matches a found name (so mistyped names cannot leak); jurisdictions never match. — *Cost if wrong:* a town that shares a party's first word is hidden; acceptable.
- **R22** — Fields that could re-fetch an author, file name, template or document property (AUTHOR, FILENAME, DOCPROPERTY, TITLE, …) are flattened to plain text. — *Cost if wrong:* those fields stop updating in the masked copy; intended.
- **R23** — A bookmark whose name contains a marked value is renamed and every reference to it updated. — *Cost if wrong:* a broken internal link in a masked copy; the AI reads text, not links.
- **R24** — Runs left outside any paragraph by unwrapped block-level revisions are deleted (the reader never sees them). — *Cost if wrong:* schema-odd text Word itself would not render is dropped.
- **R25** — Four small regressions caused by Task 7's own fix joined its second round. — *Cost if wrong:* a slightly longer round.
- **R26** — Field instructions are masked in both their raw and %-decoded forms, and the leak check scans the decoded forms too. — *Cost if wrong:* a web address whose encoding mattered is rewritten decoded; harmless to the AI.
- **R27** — Link targets and bookmarks follow the leak check's length and digit-boundary floors; dangling anchors are renamed like bookmarks. — *Cost if wrong:* none.
- **R28** — A drawing holding both a picture and a text box loses only the picture; the text box stays. — *Cost if wrong:* an odd-looking shape in the masked copy.
- **R29** — Core properties are blanked completely (including nested values, identifier and version); Word 2013 data bindings are removed; nested fields inside a flattened instruction go whole. — *Cost if wrong:* none.
- **R30** — Nested placeholders are impossible (a value found inside a placeholder is skipped); field-code names and switches are never replaced; instruction passes run once over the original text. — *Cost if wrong:* one more round on Task 13.
- **R31** — The leak check skips a field-instruction word only when it exactly equals a field-code name, switch or format keyword. — *Cost if wrong:* a false leak hit on an unusual field word (the export is blocked, not leaked).
- **R32** — Task 16 (PDF) started early for its independent part. (Amended by R73.) — *Cost if wrong:* one extra merge.
- **R33** — PDF extraction rules: lines join into a paragraph by gap and font size; headings need 12 pt or bold and larger than the body; rotated characters (diagonal watermarks) are dropped; pdfminer errors become plain messages. — *Cost if wrong:* layout only (a heading missed, a paragraph split); no leak path.
- **R34** — Placeholders are numbered after the sweep, by true first appearance in the text. — *Cost if wrong:* numbering reads differently from the plan's literal order.
- **R35** — The sweep applies "longest span wins": a swept occurrence that fully contains a shorter finding takes it over, unless the shorter one comes from your list or a stored case (your authority wins). — *Cost if wrong:* a longer variant swallows a distinct shorter value at one spot; still hidden, only the key's granularity suffers.
- **R36** — not assigned (the ledger's numbering skips it).
- **R37** — A PDF page is image-only when nothing readable remains after running lines are removed and the page has images; a file with no readable page is refused as scanned. — *Cost if wrong:* none.
- **R38** — Text in PDF layers that are off by default is dropped and the layer names reported. (Replaced by R49.) — *Cost if wrong:* some visible text of a layered PDF missing from the Word copy.
- **R39** — The running-line (repeated header/footer) key strips digits only from "page" lines or short digit-only lines; headings are never running lines. — *Cost if wrong:* a running header with a changing number in another form stays in the text; harmless.
- **R40** — Garbled PDF text (unmapped glyph codes, fake-bold doubled letters, hyphen-split words) is cleaned before detection; six cheap reviewer minors joined the round. — *Cost if wrong:* a slightly longer round.
- **R41** — Multi-column PDF pages are read line by line across the columns (a known limit of the design). — *Cost if wrong:* scrambled sentences in two-column PDFs and a value split across columns may be missed; your contracts are single-column.
- **R42** — A default never-hide word (Price, Banks, May …) is hidden when it is clearly a found person's surname at that spot, and the group is flagged for you. — *Cost if wrong:* a contract word hidden at one spot in a document that also names a person by that word; flagged.
- **R43** — Five reviewer minors (determiner-stem keying, disabled groups never sweep, non-UTF-8 list files, Unicode-aware word edges, tiny forms) joined Task 8's round. — *Cost if wrong:* a slightly longer round.
- **R44** — While analysing an original, only exact bracketed placeholders count as "already a placeholder"; altered forms such as ID-55821 are ordinary text. — *Cost if wrong:* an altered placeholder left by an earlier AI round is treated as text; harmless.
- **R45** — A contract rule's finding that ends with a legal form beats a longer model finding starting at the same place (the rule knows where the company name ends). — *Cost if wrong:* a model span that correctly extended the name is cut back.
- **R46** — At equal span the higher score wins when scores differ by 0.1 or more; otherwise the type order decides. — *Cost if wrong:* none for leaks; a placeholder type reads differently.
- **R47** — A picture page whose remaining text sits only in the top and bottom bands is an image page (stamps are not content). (Refined by R51.) — *Cost if wrong:* a margin line on a picture page is lost; you see the note.
- **R48** — A footer counts as a page-number line when it holds the page's own number ("Pagina 2 van 3"); a heading repeated verbatim on most pages is a running line. — *Cost if wrong:* a heading repeated verbatim on most pages is kept once; acceptable.
- **R49** — Hidden PDF layers are detected with a proper marked-content stack; if the layer configuration cannot be read the PDF is refused with a plain message; the report lists hidden layers and notes about text left out. — *Cost if wrong:* an exotic construction still slips through, but you see that text in the review, so nothing leaks silently.
- **R50** — The sweep also hides a found person's bare surname where it stands alone as a name; common-word surnames are flagged for you. — *Cost if wrong:* a common-word surname hidden where it meant the word; flagged.
- **R51** — A picture page counts as a scan only when its pictures cover at least half the page. — *Cost if wrong:* a small inset scan is read as a text page with stamps; nothing is lost.
- **R52** — Bare surnames are not listed as key variants; the leak check searches them with the sweep's own name-shape test instead. — *Cost if wrong:* a person referred to as "the Smith" after masking is not caught; rare, and the full name forms are always scanned.
- **R53** — Nationality and language adjectives (English, Dutch, German …) are default never-hide words. — *Cost if wrong:* a person surnamed English or French is flagged rather than hidden silently; intended.
- **R54** — A bare surname is swept only where it stands alone as a name (not inside capitalised phrases, all-caps lines, defined terms, or next to a number for month names); the determiner guard applies whatever type the engine gave the word. — *Cost if wrong:* a real surname inside a capitalised phrase stays visible; you can hide it by hand.
- **R55** — A party without a legal form whose short name is its last word ("John Smith ("Smith")") is a person; a person finding equal to a company's name joins the company. — *Cost if wrong:* an odd company typed as a person; still hidden, wrong type only.
- **R56** — Refinements of R54: engine-found one-word surnames get only the determiner guard; a line holding just a surname is a name; salutations and job titles count as separators; the capitalised-neighbour guard looks across "of/and/for". — *Cost if wrong:* an unusual phrase is hidden or left visible at one spot (the first flagged, the second visible in the review).
- **R57** — Task 8's fourth fix round resumed the same implementer rather than a fresh one. — *Cost if wrong:* one more round.
- **R58** — Model findings are cut at tabs as at line breaks, so a label after a tab never joins a name. — *Cost if wrong:* a real name containing a tab; Word never writes one.
- **R59** — "Go lean" (your instruction): at most two fix rounds per task, leftovers parked for the final review; deep reviews only for the leak- and restore-critical tasks and the final whole-branch review; plain reviews for the UI tasks. — *Cost if wrong:* polish ships as known limits in v1; they are listed below.
- **R60** — Occurrences you switched off were allowed through the leak gate by count. (Replaced by R84.) — *Cost if wrong (then):* a leftover copy of a partly unticked value could pass when its count fitted.
- **R61** — The review knows which placeholders a stored case already uses, so new groups never reuse a number. — *Cost if wrong:* none beyond an unused argument.
- **R62** — A plain always-hide value that equals an existing group's variant joins that group and keeps its type; only an explicit TYPE:value re-types a group. — *Cost if wrong:* none; you can re-type by hand.
- **R63** — Names (person, company, address, e-mail, web address, custom) are matched on word boundaries; number types keep the compact comparison with digit boundaries ("S. Hall" never hits "shall"). — *Cost if wrong:* a name leftover written with its words glued is missed by the scan; the re-scan and your review remain.
- **R64** — The leak check skips Word's own vocabulary that is never content (schema URIs, relationship types, standard part names, stock font and theme names, drawing geometry, document statistics). (Narrowed by R66.) — *Cost if wrong:* a secret equal to a font name or schema word is not caught inside those declarations.
- **R65** — Digit boundaries are judged on the text as Word shows it; one number separator may sit between a needle and a neighbouring digit; a cents tail is not a neighbour. — *Cost if wrong:* none for leaks; stricter boundaries only remove false blocks.
- **R66** — Only Word's own theme names and a fixed list of stock fonts are exempt; the cleaner resets theme names to Word's defaults; a font named after a party blocks the export with the part named. — *Cost if wrong:* a rare false block on an exotic font name.
- **R67** — Word's built-in style names are exempt for name-type needles. — *Cost if wrong:* none for content.
- **R68** — Names are also matched in a second fold that drops punctuation glued to letters ("B.V." → "bv"). — *Cost if wrong:* an occasional extra hit on a punctuation-glued word; a false block, never a leak.
- **R69** — Leak-hit contexts hide every occurrence of every key value; hits carry a count. — *Cost if wrong:* none.
- **R70** — A digit across a plain space counts as part of the same number only when it forms a thousands group. — *Cost if wrong:* a false negative in a number shape that does not occur.
- **R71** — The compact fold keeps the decimal part distinct ("1,250.00" and "1.250,00" fold alike and differ from "125,000"). — *Cost if wrong:* an amount with three decimals is folded as thousands; matches as before.
- **R72** — The decimal mark is set only when the last separator differs from the earlier ones; trailing decimal zeros are dropped; the slash is excluded from the second fold; thin spaces and typographic apostrophes are number separators. — *Cost if wrong:* none for leaks.
- **R73** — Task 15 implemented the PDF branch of loading sources itself (amends R32). — *Cost if wrong:* none.
- **R74** — New case codes never reuse a code the store already holds, readable or not. — *Cost if wrong:* one unused argument.
- **R75** — Task 18 (restore) started early for its text half. — *Cost if wrong:* one extra merge.
- **R76** — Restore removes a copied AI-instruction line the same way as the banner (both contain example placeholders). — *Cost if wrong:* none.
- **R77** — The network guard blocks internet sockets only; local inter-process sockets (used by Qt) stay allowed. — *Cost if wrong:* none for the rule "no connection leaves the laptop".
- **R78** — Banner and instruction lines are recognised after normalisation, so markdown markers, quotes or spacing changes by the AI do not keep the note in the restored text. — *Cost if wrong:* a line that is the banner plus more text is kept; its placeholders are restored correctly.
- **R79** — An unbalanced bracket at the edge of an altered placeholder belongs to the surrounding text. — *Cost if wrong:* none.
- **R80** — The guard also blocks datagram sends, server sockets and host-name lookups, and forces the domain-suffix library to its bundled snapshot. — *Cost if wrong:* none.
- **R81** — With several output files, each leak hit names the file it is in. — *Cost if wrong:* none.
- **R82** — Masking of links, field instructions and bookmarks uses the whole case key, not just the document's own findings. — *Cost if wrong:* a link rewritten for a value only the other file marked; intended.
- **R83** — When a file is added to an existing case, the merged key (stored entries plus the new review) is used for masking links and for the leak scan. — *Cost if wrong:* none for leaks.
- **R84** — The leak gate scans a twin of each output in which every key value — including places you switched off — is replaced; any hit in the twin blocks; the real output keeps your switches and reports them as "left visible on purpose". — *Cost if wrong:* masking time roughly doubles (about a quarter second per 24-page file); acceptable.
- **R85** — An existing case keeps its retention period when a file is added. — *Cost if wrong:* none.
- **R86** — A stored key value is never rewritten by a later export; a later review's spelling joins the variants. — *Cost if wrong:* an added file whose merged group had a longer name restores to the stored shorter form of the same party; both are listed as variants.
- **R87** — Task 24 (pass marks) started early; its round-trip test waited for the Word restore. — *Cost if wrong:* one extra merge.
- **R88** — Restore also replaces placeholders inside the AI's tracked deletions and insertions, so rejecting an AI change in Word can never bring a placeholder back. — *Cost if wrong:* none; a real value inside deleted text is your own document.
- **R89** — Task 25 (packaging) started early so build problems surfaced early; the final build and install repeat after the last merge. — *Cost if wrong:* one extra build run.
- **R90** — A placeholder that straddles a tracked-change boundary is rewritten as a whole-token change (both readings right, the AI's swap still visible); an unknown or unconfirmed one is left as written and listed for your check. — *Cost if wrong:* an unusual revision shape is left as the AI wrote it and reported; never a wrong value.
- **R91** — Restore offers a dry run of the Word file (every part, comments and deletions included), each item with a number, and you confirm altered placeholders one by one. — *Cost if wrong:* one extra parameter shape.
- **R92** — The app declares macOS 26 or newer, because the PySide6 wheels require it (13.0 from the brief cannot build). — *Cost if wrong:* an older Mac cannot run v1; not your case.
- **R93** — The app bundle installs exactly the locked package versions (a constraints file from uv.lock; a check before packaging). — *Cost if wrong:* a visible build-time error on a constraint, never a silent difference.
- **R94** — The bundle drops what the app never runs (developer tools, QML, the virtual keyboard, console scripts); the Qt frameworks stay. — *Cost if wrong:* a rebuild and a path list to adjust.
- **R95** — Task 24's fix round: the clause-number guard narrowed to "12.345"-shaped numbers; years before "records"; "parts" no longer a reference word; addresses continue past the country to a postcode; the web-address label needs a real domain; a secret absent from the text counts as a miss unless the page is a picture; phone labels win; a spaced hyphen between names is no separator; times are never names. — *Cost if wrong:* a slightly longer round.
- **R96** — Restore holds (lists, does not rewrite) a place merged into another tracked change; a banner inside a tracked change cannot crash the restore; confirming every altered item equals "all"; the dry run fingerprints the file and the restore refuses a file that changed since. — *Cost if wrong:* a few more items listed for you instead of rewritten.
- **R97** — Task 24's last round: units after reference words (clause, section, schedule, annex, …) are not quantities; the spaced-hyphen cut also respects never-hide terms; "2025 records" is a year after "the"/a possessive and a count after "up to/about/…"; a Dutch postcode after a spaced hyphen joins its address. — *Cost if wrong:* one more small tuning change each.
- **R98** — (session 3, process) The subagent-driven-development skill is not installed in the cloud session; the controller follows the same method by hand. — *Cost if wrong:* none.
- **R99** — (session 3) The packaging test's check that every cleanup glob matches something in the installed PySide6 runs on macOS only, because the globs name the macOS wheel's contents. — *Cost if wrong:* a misspelt cleanup glob is caught only on the Mac, which is the only place the build happens.
- **R100** — (from your outside review, finding 1) Grouping decides "same value" per type: amounts, percentages and quantities by number (decimals kept distinct) plus currency or unit, with symbols mapped to codes; e-mails and web addresses by their text with case folded and punctuation kept; phones, IBANs and identifiers by letters and digits; names as before. "EUR 1.25" and "EUR 125", "$100" and "€100", "a.b@…" and "ab@…" are separate values. — *Cost if wrong:* one value written in a spelling the fold does not recognise could get two placeholders; still hidden and still restored right.
- **R101** — (finding 2) Every picture, audio or video file is removed from the masked copy together with every reference to it (body, headers, footers, picture bullets, page background, theme), and the export is refused if any media file is still inside: the leak check cannot read pixels, so a surviving picture counts as a leftover. — *Cost if wrong:* a masked copy with a stray decorative picture is refused until you remove the picture in Word; the AI does not need pictures.
- **R102** — (finding 3) The leak check also scans XML namespace declarations and non-standard element and attribute names, and unused declarations are stripped first. — *Cost if wrong:* a false block on an exotic namespace that happens to contain a marked word.
- **R103** — (finding 4) Choosing the case for a restore: a case whose code appears in the dropped file's name wins; when two cases fit the file's placeholders equally the screen preselects nothing and asks you to choose; the case list shows code, date and original file names, and a preview shows up to five placeholder → value pairs before anything is written. — *Cost if wrong:* one more click per restore when two cases fit equally.
- **R104** — (finding 5) Word files are checked before unpacking: at most 10,000 entries, no entry over 256 MiB, at most 1 GiB in all, with a hard cap while inflating. — *Cost if wrong:* a gigantic legitimate Word file is refused; none exists.
- **R105** — (Task 24's last review) One narrow regression — a count written as a range after a reference number, "Schedule 3 - 500 pallets", shows instead of hiding — is fixed in the final fix wave rather than in a third round of the task (your two-round cap). — *Cost if wrong:* that shape is visible in the review until the wave lands; you see the text.
- **R106** — (refines R103) A case you chose by hand is never replaced by the screen; when another case fits the file better, the screen says "Another case fits this file better — check the case." and leaves the choice to you. — *Cost if wrong:* one more sentence on screen; a wrong hand pick restores nothing for placeholders that case lacks and reports them.
- **R107** — Two groups that both come from a stored case key can never be merged in a later review (the added file would restore one party as the other); a stored group keeps its value through merges and splits. — *Cost if wrong:* two placeholders for two stored parties you wanted as one; the design accepts that.
- **R108** — A case file holding the same placeholder twice is treated as unreadable rather than restored with. — *Cost if wrong:* none; the app never writes one.
- **R109** — The unused LeakBlockedError was removed; "blocked" on the export result is the contract. — *Cost if wrong:* none.
- **R110** — Co-authoring conflict marks in a Word file are resolved like tracked insertions and deletions, and their author names removed. — *Cost if wrong:* none.
- **R111** — The app turns off Python's automatic garbage collection and collects from the window's own thread on a timer, closing a rare teardown crash in the Qt bindings. — *Cost if wrong:* about fifteen lines and slightly later clean-up of cyclic garbage.
- **R112** — Web and e-mail links, link-bearing fields, editing-permission marks, stored field data and leftover author marks are removed from the masked copy; the visible link text stays (an address that lives only in a link is personal data nothing could mark). — *Cost if wrong:* the AI's copy has no clickable links; intended.
- **R113** — "[image removed]" and the other notes stand apart from the words beside them, and a found value never runs across a note. — *Cost if wrong:* none.
- **R114** — The leak gate's twin copy replaces the places of every group, keyed or not, so places you split off and switched off cannot block the export. — *Cost if wrong:* none for leaks.
- **R115** — Every wall-clock test limit was tripled so the suite does not flake on a loaded machine; a quadratic blow-up still fails. — *Cost if wrong:* a 2× slowdown goes unnoticed by the suite.
- **R116** — Five small residuals of the fix wave stay as known limits: a damaged style or settings part now makes the file refused ("not a .docx"; re-save it in Word); lower-case "schedule 3 pallets" is hidden as a count; "INCLUDE" sits harmlessly in the field list; table-of-contents links lose their link but keep their text; the leak scan costs under a second more on long files. — *Cost if wrong:* one odd refusal or one over-hidden word you see in the review; never a leak.
- **R117** — One test (the leak check over the masked corpus file dpa-01) failed once in four full runs and passed alone, under six hash seeds and in the re-run; it is recorded as unexplained rather than hidden. If it ever fails on your Mac, keep the printed hit list. — *Cost if wrong:* a rare false block you resolve by exporting again; never a leak.
- **R118** — (design pass) The new look is built the lean way on its own branch, design-v1: shell and theme first, then the review screen and the export/restore/cases screens in parallel, one review of the whole diff, one fix wave; every existing UI test adapted, none deleted; merged into mac-v1 only on your word after the smoke test. — *Cost if wrong:* one more review round.
- **R119** — Illustrations are PNG files drawn by a small script (no extra Qt module), sidebar icons are drawn in code. — *Cost if wrong:* a few extra kilobytes in the app.
- **R120** — The app follows the Mac's light or dark appearance with the two warm palettes from the mockups; the twelve placeholder tints stay only inside the document text. — *Cost if wrong:* a colour that reads worse in one mode, fixed in the UI review.
- **R121** — Settings moves out of the sidebar into the application menu (⌘,); the sidebar has exactly Mask, Restore and Cases. — *Cost if wrong:* one menu item.
- **R122** — (your instruction after the first try) Low-confidence guesses made only of ordinary words are shown, not hidden, and listed at the top of the review under "Not sure — hide?"; a guess that is a never-hide term plus filler is dropped; your Hide/Show answers are remembered in your lists with an Undo; the Settings window shows both lists with the defaults. Real names stay hidden by default. — *Cost if wrong:* an ordinary-looking phrase that was really a code name is shown until you hide it; it is listed at the top for exactly that reason.

## What Task 26 (your round trip with Copilot, Claude and ChatGPT) needs from you

Do this after the app is built and installed on your Mac (see "The remaining local step"). Use the
made-up contract `tests/corpus/generated/supply-01.docx` — never a real contract for this test.

1. In The MASK.app, open `supply-01.docx`, go through the review (nothing needs changing), and export
   it to your output folder (`~/Documents/The MASK` unless you changed it in Settings). Note the case
   code in the masked file's name, `MASKED-<CODE>.docx`. Press **Copy instruction**.
2. For each of **Copilot**, **Claude** and **ChatGPT**: upload the masked file, paste the copied
   instruction, and add the prompt "Review this agreement for risks to the Buyer and return a revised
   version as a Word file." Download the Word file the tool returns. If a tool returns text, markdown
   or a PDF instead of a Word file, copy its text and use the **Restore text** box in step 3.
3. In The MASK.app, open **Restore** and drop each returned file (or paste the text). Check that the
   preselected case is the right one — the combo shows the code, date and original file name; if the
   screen says "Several cases fit this file — choose one", choose by the code. If a list of changed
   placeholders appears ("These placeholders were changed by the AI — restore them?"), tick the ones
   that are really placeholders and press **Restore**. Expected: the report line reads
   "{n} placeholders restored, {m} need your check.", the banner is gone, no value was invented, and
   every placeholder is either restored or listed under "need your check". The restored file is
   written next to the AI's file as "<name> – restored.docx"; nothing is overwritten.
4. Record, per tool, in `docs/acceptance/2026-10-xx-round-trip.md`: did the placeholders survive
   (yes/no, and which ones the tool changed), the restore report line, anything odd. The pass mark
   (design §9) is that all three tools' files restore.
5. Commit the record: `git add -A && git commit -m "docs: Mac acceptance round trip with three AI tools"`.

What to expect: Claude and ChatGPT usually keep `[PERSON_1]`-style placeholders exactly; Copilot
sometimes reformats them (bold, or `PERSON_1` without brackets). Reformatted ones show up under
"need your check" with a checkbox; nothing is written for them unless you tick them.

## The Wi-Fi-off smoke test (Task 25, step 6 — only you can do it)

The app's own network guard covers Python-level connections only; what macOS sees is the real proof.

1. Turn Wi-Fi off (and unplug any Ethernet cable). Open The MASK.app from Applications. Expected:
   the window opens at once, says "Loading…" and reports the engine loaded within about ten seconds;
   no security dialog on the Mac that built it. The first time, macOS may ask whether the app may use
   its Keychain item (service "The MASK", account "master-key"): choose **Always Allow**. A rebuilt
   app is a new program to macOS, so it can ask again after every rebuild.
2. Drop `tests/corpus/generated/supply-05.docx` (it has a picture) and `supply-02.docx` (it has
   comments). Review, export to `~/Documents/The MASK`. If macOS asks whether the app may use your
   Documents folder, choose **Allow**.
3. Open each masked file in Word: the banner is the first line, values are `[TYPE_N]` placeholders,
   "[image removed]" stands where the picture was, there are no comments and no tracked changes, and
   File → Properties shows no author, title or company.
4. In Terminal, with the app open: `lsof -i -a -p $(pgrep -f "The MASK.app")` — it must print nothing.
5. Restore: drop one masked file (unchanged) on the Restore screen; every placeholder comes back.
6. Open the log, `~/Library/Application Support/The MASK/logs/themask.log`: counts, types and
   durations only, no words from the documents, no file names.
7. Turn Wi-Fi back on. Record the result in `docs/acceptance/2026-10-xx-mac-smoke.md`.

## Deferred minors — triage (from the final whole-branch review of 19 Oct; full detail in notes/sdd/final-review.md)

### Fixed in the final fix wave (one implementer, one re-review; rulings R100–R115)
1. One identity per value type, so "EUR 1.25"/"EUR 125", "$100"/"€100" and two e-mail spellings get their own placeholders and restore to their own values (R100).
2. Every picture or media file is removed from the masked copy wherever it is referenced, and the export is refused if one is still inside (R101).
3. XML namespace declarations and custom element names are scanned; unused declarations are stripped (R102).
4. Web and e-mail links, link-bearing fields, permission marks, field data and leftover author marks are removed from the masked copy; the link text stays (R112).
5. The "[image removed]" note no longer glues to the word before it, and a found value never runs across a note (R113).
6. Merging two groups that both come from a stored key is refused; a stored group keeps its value through merges and splits (R107).
7. A count written as a range after a reference number ("Schedule 3 - 500 pallets") is hidden again; "shall schedule 500 pallets" too where it is a one-line change (R105).
8. Word files are checked for size and entry count before unpacking (R104).
9. The three Task 14 leak-check folds (a decimal part ends a number; the byte-scan threshold; a shared fold attributed to every entry).
10. Co-authoring conflict marks are resolved like tracked changes (R110); a misplaced tracked-change record can no longer empty a paragraph on "reject".
11. Hiding text inside a switched-off occurrence now works instead of silently doing nothing; the leak gate no longer blocks after you split occurrences off and switch them off (R114); a stored key value never gains a bare surname as a variant; a case file with the same placeholder twice is listed as unreadable (R108); the unused LeakBlockedError is gone (R109).
12. Garbage collection runs from the window's own thread, closing the PySide6 teardown crash the tests had hit (R111).
13. Your name in the About panel; every wall-clock test limit tripled so the suite does not flake under load (R115).

### Parked — known limits of v1, all visible to you in the review or on the fail-closed side
- Detection shapes left to the review screen (the pass marks hold: 100 % of values and names in the made-up corpus): a surname before "in"/"on" and a capitalised word ("Smith in London") stays visible unless the model found it; a heading word or month the model tags as a person is hidden as that person (flagged); "Dear Smith" is read as a two-word person; "Smith/Jones" as a flagged company; "Price - Jones Logistics Ltd" shows "Price"; "John Carter - Managing Director" keeps "Managing" in the name; "Annex 2 Units of Measure" may be hidden as a flagged company; "Either/Neither Party", "GMT"/"EC", "the Federal Republic of Germany" appear as flagged companies; year ranges before "records"; two parties in one hyphenated header share a placeholder; a company short name that is a contract word ("Quality" of Quality Foods Ltd) stays visible; the model misses very short first names ("Jo Banks"). Cost if left: a value visible in the review that you hide by hand, or a flagged row you dismiss.
- Leak check, all on the fail-closed side: an exotic namespace or font named after a party, a hyphenated word that folds onto a short company name, a very long paragraph (> 8,192 characters) with field words, a damaged theme part ("not a .docx"), a link counted twice, "10.00 %" counted as checkable, cents matching ("EUR 1,250.00" also hits "1,250.05") — each can block an export you then resolve in Word; none can leak. The byte scan reads UTF-8/UTF-16 only (after the wave the only binary parts left are embedded fonts).
- Review screen: merging a group you never-hid into an enabled group takes the term back into the merged variants (the twin gate still masks those places); an always-/never-hide entry stays in memory if the lists file cannot be written until the next save.
- Restore (cosmetic, in your own file): a banner paragraph that also holds a bookmark or a tracked insertion is emptied rather than deleted; a text-box backup copy that differs from its main copy is restored without a note; if the AI deletes one word of the banner the restore shows a tracked change for it; a "> " quote line or a numbered-item banner stays; a dropped "[" leaves a stray "]".
- Word cleaner: unbalanced field markers after a partially hidden field (Word repairs them); the external transform path in settings.xml (scanned for marked values); compressed or exotic binary parts.
- PDF: a page-number footer set wholly in bold is kept on every page; a page holding only a small picture and a stamp drops the picture without a note; multi-column pages read line by line.
- Packaging (build tooling only, nothing the running app does): `check_bundle_lock` exits with a traceback instead of code 2 on an unreadable line; icon files not validated by a test; `make_icon` hides iconutil's errors; an empty platforminputcontexts folder; Designer/SQL/QML payload still in the bundle (matters only if the app leaves your Macs — Windows-phase SBOM).
- Code structure for the Windows phase: duplicated relationship plumbing in the cleaner, three vocabularies defined twice, `_count` copied four times, large modules (leakcheck 1,572 lines, contract_rules 1,535, cleaner 1,060, grouping 831, restore_screen 754, review_screen 710, main_window 617), test inflation in the early tasks, a few stale docstrings and the README's BIC check-digit remark.

### No longer applies (verified at the final review)
MaskPlan validation (done in Task 2's model since), the zip archive comment (never copied into a masked file), `int()` on very long digit runs (every call guarded), the README's wording on export and restore (fine), the automatic case choice (R103/R106 verified in the code and the 99 restore-screen tests).

## Using v1 safely — what no one-line change fixes
1. The MASK hides values, not the story: industry, places, unusual terms and clause structure can still identify the parties (design §10). Read the masked copy once before uploading it.
2. The leak check proves that marked values are gone; it cannot find what nobody marked. The review screen is the net: look at the "check" rows, at headers and footers (shown after the body) and at anything the model typed oddly.
3. Restore writes a group's full form ("Mr Smith" comes back as "John Smith"; a national phone number as the international form). Intended.
4. Restored files and copied text hold the real values. The restored file is written next to the AI's file: if that folder syncs (iCloud Drive, OneDrive, a synced Downloads), the restored contract syncs too. Keep the AI's downloads in a local folder. Copied text is on the clipboard in clear.
5. Copilot with a Microsoft 365 licence can read your OneDrive, SharePoint and Outlook originals; the masked copy does not hide those (design §10).
6. The always-hide list is a plain text file (`~/Library/Application Support/The MASK/lists.json`, readable by your account only): put product and project code names there knowing that.
7. Keys die with the Mac or the user account and expire after the retention period (30 days by default, up to 365 in Settings; the purge runs at every start). Set a longer retention before a long-running matter; a deleted or expired case means its masked files can never be restored.
8. A font or theme named after a party blocks the export: re-save the file from Word with a standard font. A damaged theme part is refused as "not a .docx".
9. PDFs: only selectable text is read; image-only pages are listed and left out; multi-column pages read line by line; nothing hidden in the PDF (comments, form fields, attachments, properties) is carried over.
10. Do not mask a masked copy again: placeholders already there are respected and numbering continues, but a second round makes the key harder to follow.
11. "No network" rests on two things: the Python-level guard the suite runs under, and your own Wi-Fi-off smoke test of the built app with `lsof`. Qt and macOS frameworks are outside the guard; nothing in the app calls them for the network, but the monitor is the proof.
12. The built app is ad-hoc signed: a rebuilt app is a new program to the Keychain and macOS may ask again. There is no CI; the local suite is the gate (an option for the Windows phase).

## The remaining local step (your Mac; the cloud cannot build or sign a Mac app)

1. In Terminal: `cd ~/Developer/the-mask && git fetch origin && git checkout mac-v1 && git pull`
   (mac-v1 must be at 4bbde49, the head named above), then `uv sync --locked`.
2. The About panel shows your name, "Alican Yazdic" (set in `src/themask/about.py` during the final
   fix wave, on your instruction); nothing to do here unless you want it spelt differently.
3. Optional but worth it: `uv run pytest -q` — on the Mac the macOS-only tests (vtool, iconutil,
   codesign, the cleanup-glob check) run as well.
4. `bash packaging/build_mac.sh` — it starts from scratch, downloads Briefcase's Python support
   package and the wheels once, checks the bundle against `uv.lock` (expect "74/74"), and ends with
   `build/themask/macos/app/The MASK.app` (about 510–550 MB) and `dist/The MASK-0.1.0.app.zip`
   (about 183 MB). Check: `du -sh "build/themask/macos/app/The MASK.app"` under 600M, and
   `codesign -dv --verbose=2 "build/themask/macos/app/The MASK.app" 2>&1 | grep Signature` shows
   `Signature=adhoc`.
5. Install: quit and trash any older "The MASK.app" in Applications first (README, "Install it on this
   Mac"), then `ditto "build/themask/macos/app/The MASK.app" "/Applications/The MASK.app"` and open it.
6. Then the Wi-Fi-off smoke test above, then Task 26.
7. Merging `mac-v1` into `main` is your decision; the controller has not done it and will not.

## After v1: the design pass you asked for

You asked (19 Oct) for the app to feel integrated, charming, easy to use — "the Apple way". That is a
separate pass after the functional build and the smoke test, and we talk it through first. Points to
decide then: the native macOS look (system font, spacing, light and dark mode), one window with a
sidebar instead of tool-bar screens, drag-and-drop everywhere, progress shown in the window rather
than in dialogs, icons, plain-language wording of every message, keyboard shortcuts, a first-run
walkthrough. Nothing in the current build stands in the way of it: every screen is a separate
module and the tests drive the screens through their widgets, not their looks.
