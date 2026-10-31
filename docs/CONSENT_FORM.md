# LAXTHYA-Ink — Handwriting Capture Consent

**Version:** `2026-10-30-v1` (must match `capture.consent_version` in `config.yaml`; bump both whenever this text changes.)

> **DRAFT for the owner to review before first use.** Items in [brackets] are for the owner to fill in. This is plain-language wording, not legal advice. Check the data-protection rules that apply where you and the writers live, and whether writers under 18 need a guardian's consent.

---

## What this is

[Operator name] is building a system in which a pen mounted on a 3D printer writes text in a person's own handwriting. To teach it your handwriting, you will write some set texts on an iPad with an Apple Pencil.

## What is recorded

- The movement of the pencil: its position, the time, how hard you press, and its tilt, many times a second. This includes the movement just above the screen between strokes.
- The texts you were asked to write, which writing style you were asked for (natural, cursive, or printed), and the iPad and Pencil used.
- A writer ID such as `W001`. The operator may also keep a private **note** about you (for example your name). The note is kept only in the operator's database. It is **never** put in backups or shared files.

Nothing is recorded by a camera or a microphone.

## What it is used for

1. **Required for taking part — this project.** To build a model of **your** handwriting, to make the printer write in it, and to test and improve the system. The model is made for you. It will not be used to write as you except as you direct, and it will not be used for anything that must be signed by you or that pretends to come from you.
2. **Optional — research sharing.** To share your recorded handwriting, **without your name or note**, with other researchers working on handwriting.

You can take part with only box 1 ticked. Handwriting movement can still identify a person even without a name, which is why sharing is a separate choice.

## A model of your handwriting can imitate you

A model trained on your handwriting could in principle be misused to forge your writing. The operator will keep your data and your model only on [the operator's own computer and backups] and will not give the model to anyone else. If you tick box 2, the *recorded handwriting* (not your model) may go to other researchers.

## Where it is kept and for how long

On [the operator's own computer, plus backups at ___]. Kept until you ask for it to be deleted [or for ___ years, whichever is sooner].

## Your rights

- Taking part is **voluntary**. You can stop at any time, even in the middle of a session.
- You can **ask for your recordings, your note and any model trained on your handwriting to be deleted**, by contacting [contact]. The operator will do this and tell you when it is done.
- **Limit of deletion:** if you ticked box 2 and your recordings were already shared, the operator cannot reach other people's copies. The operator will tell you who received them.
- You can ask what has been recorded about you.

## Your choices

- [ ] **1. I agree** to my handwriting being recorded and used for this project, as described above. *(Required to take part.)*
- [ ] **2. I also agree** that my recorded handwriting may be shared, without my name or note, with other researchers. *(Optional.)*

Writer ID: ______________  Date: ______________

---

## How the app records this

The capture app shows this text and the two tick-boxes before the first stroke. It stores the writer ID, both choices, the consent version and the time. If box 1 is not ticked, the app does not create the writer (the database refuses it). Only writers who ticked box 2 are included in any shared export.
