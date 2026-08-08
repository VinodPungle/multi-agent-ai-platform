# Diagrams

Diagrams live **next to the prose they explain**, not in a separate gallery:

- Architecture and sequence diagrams → [`../architecture/`](../architecture/)
- Decision context → [`../adr/`](../adr/)
- The target architecture → [`../../.claude/architecture.md`](../../.claude/architecture.md)

A diagram separated from its explanation gets updated separately from it, and
then stops being true.

This directory exists because `architecture.md` §67 lists it, and holds only
standalone visual assets that belong to no single document — a poster-style
system map, a printable topology.

## Conventions

- **Mermaid, always.** It renders in GitHub and most editors, and it diffs as
  text. A PNG cannot be reviewed in a pull request.
- **Show the mechanism.** Boxes and arrows that restate the directory listing add
  nothing. Show what calls what, in what order, and where the boundaries are.
- **Date and scope every diagram.** Undated, it becomes impossible to trust once
  the code moves.
- **Update it with the code.** A stale diagram is worse than no diagram: it is
  confidently wrong.

If a raster image is unavoidable — a screenshot, a vendor reference — commit the
source alongside it so it can be regenerated.
