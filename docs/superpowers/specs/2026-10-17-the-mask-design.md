# The MASK — Design

**Date:** 17 October 2026 · **Status:** Draft 2 (owner's answers added), waiting for the owner's approval · **Owner:** [owner's name — shown in the app's About screen]

## 1. In one paragraph

The MASK is a desktop app for Mac and Windows that lets you use any AI tool (Microsoft Copilot, Claude, ChatGPT and others) on a confidential document without the AI ever reading the confidential parts. Before you upload a contract, The MASK replaces personal data and business secrets with placeholders such as `[PERSON_1]` or `[AMOUNT_2]`, and keeps the real values in an encrypted key on your own computer. When the AI gives you back a Word file, The MASK puts the real values back in. Everything happens on the laptop. Nothing is ever sent anywhere.

## 2. Why it exists

The owner reviews agreements between two parties and wants AI help with them: spotting risks, suggesting wording, summarising. The agreements contain personal data (names, contact details, signatures) and business secrets (the agreement price, fees, bank details and similar). The owner does not want any AI tool to read those values, but still wants its help with everything else.

Two facts make this workable:

- For legal review, the exact values rarely matter. When one does, the owner tells the AI in their own words.
- A missed secret (a leak) is much worse than hiding too much.

The owner wants this as their own tool, under their own name, for private use and inside Bunzl. Inside Bunzl, IT must approve it before it can be installed.

## 3. Who it is for

- **The owner.** Reviews contracts. Uses a Mac and a Bunzl Windows laptop.
- **Bunzl colleagues.** Later, for the same kind of work. *(Exactly who is not yet known.)*
- **Bunzl IT.** Must approve the app, so they need to be able to check that it is safe without trusting anyone's word.

## 4. How it works: the round trip

**1. Mask.** Drag a contract (Word, or a PDF with real text) into The MASK. It finds personal data and business secrets and shows them to you. You untick false alarms, add anything it missed, and save. The MASK writes a masked Word copy with a neutral file name and keeps the key.

**2. Ask any AI.** Upload the masked copy to Copilot, Claude, ChatGPT or any other tool. Paste the short instruction The MASK gives you ("keep the placeholders exactly as written") along with your question. Download the Word file the AI makes: a revised contract, a review memo, a table of issues.

**3. Restore.** Drag the AI's Word file into The MASK. It replaces each placeholder with its real value and saves a restored copy. It lists anything it could not restore with certainty, so nothing goes wrong silently.

| What the AI sees | What you get back |
|---|---|
| `[COMPANY_1]` shall pay `[AMOUNT_1]` to `[COMPANY_2]` within 30 days. | Northwind Trading B.V. shall pay EUR 1,250,000 to Acme Supplies Ltd within 30 days. |

## 5. Goals, non-goals, anti-goals

### Goals

1. **No leak.** No marked value appears anywhere in the masked file: visible text, hidden parts, file properties or file name.
2. **Faithful restore.** Every placeholder in the AI's Word file gets its correct real value, and the AI's formatting is kept. Anything uncertain is shown to the owner, never guessed.
3. **Any AI tool.** Works with files in and files out. No plug-ins, connectors or links to any AI service.
4. **IT can approve it.** Offline, transparent and documented, and packaged the way Bunzl IT requires.
5. **Mac and Windows**, with the same features.
6. **Quick and simple.** A 30-page contract is analysed in under a minute on an ordinary office laptop, and each step takes a few clicks.

### Non-goals for version 1

- Languages other than English. The design must allow adding languages later without a rewrite.
- Scanned PDFs or photos of paper, which need text recognition. The MASK says clearly that it can't handle them yet.
- Other formats: old .doc, .rtf, .odt, Excel, PowerPoint, e-mails.
- Talking to AI tools directly (APIs, plug-ins, connectors).
- Sharing keys between people or devices; anything in the cloud.
- Turning the AI's suggestions into tracked changes in the original (see section 12).
- PDF output.

### Anti-goals (a failure, even if everything else works)

- A real value reaches an AI tool by any route.
- The app makes any network connection, ever, including update checks and crash reports.
- Restore puts the wrong real value into a placeholder (for example, swaps two people) without a warning.
- The key is stored unencrypted, or can leave the laptop.
- So much is hidden that the AI can't help, e.g. hiding "Buyer", "the Agreement", clause numbers or notice periods.
- The original file is changed in any way.
- The app needs things IT would refuse: admin rights to run, background services, open network ports.

## 6. Constraints

- Fully offline. All models and data ship inside the installer.
- macOS on Apple silicon (Intel Macs nice-to-have) and Windows 10/11 64-bit, on ordinary office laptops: CPU only, 8 GB RAM.
- Only licences a company will accept: permissive (MIT, BSD, Apache-2.0), or LGPL used as a library. No GPL or AGPL. For example, PyMuPDF (AGPL) is out, and so are GPL-only Qt add-on modules.
- No local web server and no listening ports.
- Inputs: .docx and text-based .pdf. Masked output: .docx. Restore input: .docx, plus pasted text.
- English first.
- Name: **The MASK**, credited to the owner. Arthur Mask is not used, and none of its code is used.
- Development and testing use made-up documents only, never real contracts.

## 7. Decided by the owner

These came from the owner. They are not the builder's to change.

- Their own tool, under their own name. Not Arthur Mask, and not built on it.
- To be used inside Bunzl as well. Bunzl IT must approve it.
- Must work the same way with every AI tool: Copilot, Claude, ChatGPT and others.
- The owner uploads the file to the AI and downloads a Word file back.
- Hide both personal data and business secrets, e.g. the agreement price.
- A leak is worse than hiding too much. Values rarely matter; the owner tells the AI when one does.
- Must run on Mac and Windows.
- English first; documents may come in any language later.
- Inputs are mostly PDF and Word.
- Name: The MASK.
- To review the other side's redline, both versions (before and after) are masked into one case and the AI compares them.
- Contracts are not protected by encrypting sensitivity labels or passwords.
- Mac first, so the owner can try it; Windows follows. Both are part of version 1.
- No installer if it can be avoided: just put the app on the Mac and on the Windows laptop.

## 8. Design decisions

These are the designer's calls, not the owner's. The owner may overrule any of them.

### 8.1 Placeholders

- Format `[TYPE_N]`: square brackets, upper-case type, underscore, number. Types: `PERSON`, `COMPANY`, `AMOUNT`, `PERCENT`, `QUANTITY`, `EMAIL`, `PHONE`, `ADDRESS`, `IBAN`, `ID` (VAT, registration, passport and similar numbers), `URL`, `CUSTOM` (the owner's own words).
- Why this format: AI tools keep it well, it is easy to find again, and it still reads naturally ("`[COMPANY_1]` shall indemnify `[COMPANY_2]`").
- The same value gets the same placeholder everywhere in a case. Variants are grouped: "Acme Supplies Ltd", "Acme" and "ACME" all become `[COMPANY_2]`; "John Smith", "Mr Smith" and "J. Smith" all become `[PERSON_1]`. The owner can merge or split groups during review.
- Restore puts back the group's full form (e.g. "John Smith", even where the original said "Mr Smith").
- These stay visible by default because the AI needs them: defined terms (Buyer, Supplier, Party, Agreement, Schedule…), clause numbers and headings, dates, durations and notice periods. The owner can still hide any of them by hand.

### 8.2 What it finds (English, version 1)

On by default:

- **People:** names, including those in signature blocks, "Attention:" lines and notice clauses.
- **Contact details:** e-mail addresses, phone numbers, postal addresses, the parties' web addresses.
- **Companies:** company names, including legal forms (B.V., N.V., GmbH, Ltd, Inc., LLC, S.A., plc…). The owner's own company is hidden too; the owner can add it to the never-hide list.
- **Money:** amounts in any common form (EUR 1,250,000 · €1.25m · 1.250.000,00 · "one million euros"), and all percentages.
- **Quantities and service levels:** volumes and quantities with units (units, pieces, cartons, pallets, kg, tonnes, litres), minimum order quantities, volume commitments, capacities, rebate tiers and service levels. In supply agreements these are often as sensitive as the price. Durations ("30 days"), dates and clause numbers are not quantities, so they stay visible. *(Designer's call, added after review.)*
- **Bank details and ID numbers:** IBAN (checksum-checked), BIC/SWIFT, account numbers, VAT and company registration numbers, passport, ID and social-security numbers, card numbers.
- **The owner's own words:** an "always hide" list, for all documents or for one case (e.g. project code names, product names, site names).

A **never-hide** list holds legal vocabulary and defined terms, to keep the document useful.

How it finds them, in four layers plus a final sweep:

1. Pattern rules with validation (formats, checksums).
2. An English name-finding model for people, companies and places.
3. Contract-aware rules: the parties defined at the start ("between X … and Y"), signature blocks ("By:", "Name:", "Title:"), notice clauses.
4. The owner's always-hide and never-hide lists.
5. Sweep: once a value is found anywhere, every other occurrence of it, and of its variants, is hidden too.

When unsure, hide. Never hide a never-hide term.

### 8.3 Review before export (mandatory)

Nothing is saved for upload until the owner has reviewed it. The review screen must let the owner:

- see the document text with each find highlighted (colour by type), next to a list grouped by value ("Acme Supplies Ltd — 14 times — `[COMPANY_2]`");
- untick a whole group or a single occurrence;
- select missed text and hide it (all its occurrences follow);
- merge or split groups;
- add words to the always-hide or never-hide list;
- spot low-confidence finds, which are hidden but marked "check".

### 8.4 Building the masked copy

**Protected files:** the owner's contracts are not encrypted or password-protected. If one is, The MASK says so and asks for an unprotected copy.

**From Word (.docx):**

- Work on a copy. Never touch the original.
- Keep layout, styles, tables and clause numbering. The AI needs the clause references.
- Replace marked values everywhere text can live: body, tables, headers, footers, footnotes, endnotes, text boxes, content controls, fields, and link targets (e.g. `mailto:`).
- Remove:
  - comments;
  - file properties (author, last modified by, company, manager, title, subject, keywords) and custom properties;
  - custom XML and document variables;
  - hidden text;
  - images and embedded objects (signatures, logos, embedded spreadsheets) and their alt text;
  - template paths;
  - revision authors and dates.

  Each removed image becomes a visible "[image removed]" note.
- Tracked changes are accepted in the masked copy, so the AI sees the final text.
- **Reviewing a redline** (owner's choice): the AI compares two masked versions instead of reading tracked changes. When a Word file contains tracked changes, The MASK offers to make both versions from it: "before" (all changes rejected) and "after" (all changes accepted), masked with the same placeholders. The owner can also drop two separate versions into one case. *(Making both from one file is the designer's call.)*
- A short note goes at the top: "Confidential values in this document are replaced by placeholders such as `[COMPANY_1]`. Keep them unchanged." This helps any AI even if the owner forgets the instruction line. Restore removes the note if the AI copies it.
- Neutral file name, e.g. `MASKED-K4F7.docx`, because original file names often contain party names.

**From PDF:**

- Only PDFs with real, selectable text. Image-only pages are left out and listed ("page 14 is an image — not included"). A fully scanned PDF is refused with a clear message.
- The PDF itself is never edited. Text is read in reading order (paragraphs, headings, tables where possible), placed in a fresh Word file, then masked as above. The layout gets simpler but the content is complete. Nothing hidden in the PDF (comments, layers, form fields, attachments, properties) is carried over.
- Lines repeated on every page (running headers, footers, page numbers) appear only once.

### 8.5 Leak check (mandatory, blocks saving)

Before the masked copy is saved, The MASK opens the finished file and searches every part of it (all internal parts, links, properties and the file name) for every marked value and its variants. The search ignores case, spacing and punctuation differences (an IBAN with or without spaces; 1,250,000 vs 1.250.000). Any hit blocks saving and shows where it is. The MASK also re-runs detection on the masked copy and shows anything new.

In plain words: the leak check proves that everything marked is really gone, everywhere. It cannot find a secret that nobody marked. That is the job of detection plus the owner's review.

### 8.6 The key

- One key per case: each placeholder with its real value and variants, plus the date, the source file names and a fingerprint of the masked file(s).
- Stored encrypted in the app's own data folder. The encryption key sits in the operating system's secure store (macOS Keychain, Windows Credential Manager). There is no password to remember, and only that user on that laptop can open it.
- Deleted automatically after 30 days (adjustable). The owner can delete one case or all cases at any time.
- No export of keys in version 1. A key cannot move to another laptop.
- Masked files are safe to share. The key and the restored files are the sensitive things.

### 8.7 Restore

- Input: the AI's .docx. There is also a paste box: paste the AI's chat text and get restored text back.
- The owner picks the case. The most recent case is preselected, and the case whose placeholders match best is suggested.
- Placeholders are replaced everywhere in the file (body, tables, headers, footers, footnotes, any comments the AI added) and the AI's formatting is kept. This includes placeholders that Word has split across formatting runs.
- Small AI changes are caught: missing brackets (`PERSON_1`), spaces (`[PERSON 1]`), lower case, escaped brackets (`\[PERSON_1\]`), bold markers. These are listed and restored only after one confirming click.
- Placeholders that are not in the key (e.g. the AI invented `[PERSON_9]`) are listed and left as they are.
- The MASK's note is removed if the AI copied it.
- The restored file is saved as a new file (`<original name> – restored.docx`). Nothing is overwritten.
- At the end, a short report, e.g. "57 placeholders restored, 2 need your check."

### 8.8 The instruction for the AI

A copy button gives a short instruction to paste with the question, for example:

> This document uses placeholders such as [PERSON_1] and [AMOUNT_2] instead of confidential values. Keep every placeholder exactly as written, including the square brackets, in your answer and in any file you create. Do not guess the real values. Please give your result as a Word (.docx) file.

### 8.9 Cases with several files

A case can hold several files (e.g. a contract and its annexes, or the before and after versions of a redline) that share one key, so the same company gets the same placeholder in every file. The owner can drop several files at once, or add a file to an existing case.

### 8.10 Platform and technology

- One codebase: a desktop app for macOS and Windows.
- A Python core, because Python has the best offline tools for finding personal data and good Word and PDF libraries. A native desktop interface built with Qt (PySide6, LGPL): no browser, no local server, no open ports.
- Detection: Microsoft Presidio (MIT) as the framework, with a bundled English name-finding model (e.g. a spaCy English model, MIT). The builder may use a stronger model run through ONNX Runtime (MIT) if it fits the licence and size limits.
- Word: python-docx and lxml, working at the XML level. PDF: pdfplumber / pdfminer.six (MIT) or pypdfium2 (Apache-2.0 / BSD).
- Encryption: `cryptography`. OS secure store via `keyring`.
- **Mac: no installer.** The app is a single item, The MASK.app, that the owner copies into Applications. Built on the owner's own Mac, it opens normally without a paid Apple certificate. Copied to a different Mac, macOS warns once (System Settings → Privacy & Security → Open Anyway).
- **Windows: a portable app folder** that runs without installing (copy the folder, start The MASK.exe), if Bunzl IT allows it. If IT requires a signed, centrally deployed package (.msi), it is built in the Windows phase, together with a code-signing certificate. Either way, it must not be flagged by Microsoft Defender.
- Size target: under about 600 MB.
- No automatic updates. A new version is copied over the old one, or delivered by IT.
- No telemetry. A local log that never contains document content.

### 8.11 The IT approval pack

Delivered in the Windows phase (8.12):

- A one-page security summary: what the app does, and what it never does.
- A diagram of where data goes (it never leaves the laptop).
- A full list of components and their licences (a software bill of materials, SBOM).
- Where data is stored, how it is encrypted, and how it is deleted.
- How IT can verify "no network" themselves: block the app in the firewall, or run it on an offline machine and watch a network monitor.
- Access to the source code.

The owner may also use the pack for Bunzl's own assessment of the tool (for example a DPIA).

### 8.12 Order of work (owner's choice)

Both platforms are part of version 1, built in this order:

1. **Mac phase.** The full app on the Mac, so the owner can try it as early as possible: on the made-up test contracts first, then on their own work.
2. **Windows phase.** The same app on Windows, the IT approval pack, and whatever packaging and signing Bunzl IT requires.

Asking IT the questions in section 14 early saves time, because IT approval is the slowest step.

## 9. How we know it works

Testing uses a made-up set of at least 20 realistic English contracts (supply, services, NDA, data-processing agreements), in both Word and PDF, with tables, headers and footers, comments, tracked changes, images and file properties. Each one comes with a hand-made list of every secret in it.

| Check | Pass mark |
|---|---|
| Marked values left anywhere in a masked file | 0, always |
| Pattern-type items (e-mail, phone, IBAN, ID numbers, amounts) found automatically, before review | ≥ 99% |
| Names, companies and addresses found automatically, before review | ≥ 95% |
| Never-hide terms hidden by mistake | 0 |
| Unchanged placeholders restored correctly | 100% |
| Altered placeholders (the kinds listed in 8.7) caught | 100% |
| Wrong substitutions | 0 |
| Full round trip with Copilot, Claude and ChatGPT on the made-up contracts | placeholders survive and restore |
| 30-page contract analysed on an 8 GB office laptop, Mac and Windows | under 60 seconds |
| Works with networking disabled; a network monitor shows no connections | yes |
| Mac: the app opens on the owner's Mac with no security warning | yes |
| Windows: accepted by Bunzl IT and not flagged by Defender | yes |

## 10. Known limits and risks

- Detection is never perfect. The review step is the safety net, and the owner stays responsible for what gets uploaded.
- Context can still give things away. With names hidden, unusual details (industry, locations, unique terms) may still hint at who the parties are. The MASK hides values, not the story.
- **Microsoft 365 Copilot can already read the owner's OneDrive, SharePoint and Outlook** (with a full Microsoft 365 Copilot licence). Masking the uploaded copy does not hide originals stored there, and Copilot could bring real values into its answer from those sources.
- An AI may change or drop placeholders. Restore flags changes, but cannot recover text the AI left out.
- Hiding values means the AI can't judge them (e.g. whether a price or a liability cap is reasonable). This is intended; the owner adds context by hand.
- Restore uses a value's full form, so "Mr Smith" may come back as "John Smith".
- Copying restored text puts real values on the clipboard. If Windows clipboard sync is turned on, it may upload them.
- Losing the laptop or the user account means losing the keys for open cases. This is by design: masked files alone reveal nothing.
- Turning a PDF into Word can lose complex layout (multi-column pages, footnote positions).

## 11. Left to the builder

- Which name-finding model, the thresholds, and how variants are grouped, within the licence, size and pass-mark limits above.
- Screen layout and visual design, within the review requirements in 8.3.
- Word internals: split formatting runs, fields, keeping numbering intact.
- How PDF text, reading order and tables are extracted.
- The key file's format.
- Packaging tools and the build pipeline for both operating systems.
- Creating the made-up test contracts.

## 12. Later (version 2 and beyond)

- More languages (Dutch, German, French, Turkish…).
- Scanned PDFs, with offline text recognition.
- Applying the AI's suggested edits to the original Word file as tracked changes, with the real values intact: ask the AI for an "old text → new text" table and apply it. Arthur Mask works this way. Until then, use Word's built-in Compare on the original and the restored AI version.
- Excel, PowerPoint, e-mail.
- Shared always-hide lists for a team.
- Comments from the document, shown as a masked list next to the text.

## 13. Prior art

Arthur Mask (ArthurLegal), installed on the owner's Mac, was inspected on 17 October 2026. It swaps values for tags like `{{KİŞİ-01}}`, requires a human review before a document is "ready", uses a local multilingual model (GLiNER multi-PII) plus Presidio and OCR, and returns AI edits as Word tracked changes through a Claude connector. The owner chose not to use it: they want their own tool, under their own name, for use at Bunzl, working with any AI tool through files. Ideas worth keeping: typed placeholders, the mandatory review, and tracked-change apply (for later). No code is taken from it.

## 14. Questions: answered and still open

Answered by the owner on 17 October 2026:

1. **Tracked changes and comments:** option (b). Both versions are masked into one case and the AI compares them (see 8.4).
2. **Sensitivity labels and passwords:** no. Contracts are not protected that way.
3. **Order:** Mac first, so the owner can try it; Windows follows. Both are finished as part of version 1 (see 8.12).
4. **Installer:** none wanted if avoidable. Mac: a plain app with no installer. Windows: a portable folder if IT allows it (see 8.10).

Still open, and none of it blocks the Mac phase:

- The owner's name as it should appear on the About screen.
- For the Windows phase, questions for Bunzl IT:
  - how they deploy software (Intune or similar);
  - whether a portable app is allowed, or laptops run only signed or approved code (AppLocker/WDAC);
  - whether the laptops are x64 or ARM;
  - whether a standard Bunzl test laptop can be borrowed.
