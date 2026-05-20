# Skill: Manage and Compile Devin Presentation Slides

Use this skill file to maintain, build, and serve the presentation slides for the "Devin Autonomous Issue Solver".

## Prerequisites
- Node.js and npm installed on the host.
- No local installation of Marp is required; commands run via `npx`.

## Key Commands

Always run these commands from the `presentation/` directory.

### 1. Compile Slides to HTML (Recommended)
This generates a self-contained, interactive HTML slide deck (`index.html`):
```bash
npx -y @marp-team/marp-cli slides.md -o index.html
```

### 2. Live Watch Mode (For Editing)
This watches `slides.md` for changes, compiles them on the fly, and supports live reloading:
```bash
npx -y @marp-team/marp-cli -w slides.md -o index.html
```

### 3. Compile Slides to PDF
To generate a static PDF version of the deck:
```bash
npx -y @marp-team/marp-cli slides.md --pdf -o slides.pdf
```

### 4. Serve the Presentation Locally
To share or present the HTML deck on a local port:
```bash
python3 -m http.server 8080 --directory .
```
Then access the slides at: http://localhost:8080/index.html

## Slide Modification Rules
- Every slide must be separated by `---` on its own line.
- Custom style blocks are preserved at the top of `slides.md` to maintain the premium theme styling.
- Keep bullet points concise to avoid wrapped lines.
- Ensure the ASCII architecture diagram is properly aligned in markdown code blocks.
