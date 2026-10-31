# Bharmafills — UI/UX Design Specification

> **Document Status**: Active / Canonical Baseline
> **Preset**: shadcn/ui Nova Preset with Base UI
> **Theme**: Light Mode / Professional Neutral SaaS

---

## 1. Design Philosophy

Bharmafills is designed as an analytical research intelligence tool. Its aesthetic prioritizes:
- **Clarity over Flashiness**: High contrast, minimal visual noise, and clean typography.
- **Cognitive Ergonomics**: Information density balanced with ample breathing room.
- **Predictable Affordances**: Modals, buttons, dropdowns, and badges follow strict standard behaviors across viewports.
- **Zero Unwanted Dark Mode**: Strict `color-scheme: light` enforcement by default, with scoped class-based `.dark` support preserved for future user toggles.

---

## 2. Color System (Nova Palette Tokens)

Defined in [frontend/src/index.css](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/frontend/src/index.css) using OKLCH color space for perceptually uniform lightness:

| Token Name | OKLCH Value | Approximate Hex | Usage / Contrast |
| :--- | :--- | :--- | :--- |
| `--background` | `oklch(1 0 0)` | `#ffffff` | Page background |
| `--foreground` | `oklch(0.145 0 0)` | `#171717` | Primary text, headings (16.5:1 on white) |
| `--card` | `oklch(1 0 0)` | `#ffffff` | Elevated surface background |
| `--card-foreground` | `oklch(0.145 0 0)` | `#171717` | Text inside cards |
| `--primary` | `oklch(0.205 0 0)` | `#262626` | Primary action buttons, active navigation indicator |
| `--primary-foreground` | `oklch(0.985 0 0)` | `#fafafa` | Text on primary buttons |
| `--muted` | `oklch(0.97 0 0)` | `#f5f5f5` | Secondary backgrounds, category tag pills |
| `--muted-foreground` | `oklch(0.556 0 0)` | `#737373` | Subtitles, helper text, timestamps (4.6:1 contrast) |
| `--border` | `oklch(0.922 0 0)` | `#e5e5e5` | Container borders, dividers, card outlines |
| `--destructive` | `oklch(0.577 0.245 27.325)` | `#dc2626` | Delete actions, destructive alerts, error text |
| `--ring` | `oklch(0.708 0 0)` | `#a3a3a3` | Keyboard focus ring outlines |

### Status Badge Palette
Defined in [frontend/src/features/research/utils/researchStatus.js](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/frontend/src/features/research/utils/researchStatus.js):
- **Draft**: `bg-amber-500/10 text-amber-700 border-amber-500/20`
- **In Progress**: `bg-blue-500/10 text-blue-700 border-blue-500/20`
- **Completed**: `bg-emerald-500/10 text-emerald-700 border-emerald-500/20`
- **Archived**: `bg-zinc-500/10 text-zinc-700 border-zinc-500/20`

---

## 3. Typography (Geist Variable)

- **Font Family**: `'Geist Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif`
- **Headings**:
  - `h1`: `text-2xl sm:text-3xl lg:text-4xl font-bold tracking-tight text-foreground`
  - `h2`: `text-lg font-bold tracking-tight text-foreground`
  - `h3`: `text-base font-bold text-foreground`
  - Eyebrows: `text-xs font-bold uppercase tracking-wider text-muted-foreground`
- **Body Text**: `text-sm leading-relaxed text-foreground/90`
- **Subtitles & Descriptions**: `text-xs sm:text-sm text-muted-foreground`
- **Overflow Rule**: All user-authored strings (titles, questions, descriptions) must include `break-words` to eliminate horizontal container clipping.

---

## 4. Spacing & Layout Principles

### 4.1 Responsive Breakpoints (Tailwind CSS v4)
- **Mobile (`< 640px`)**: Single-column cards, hamburger topbar button, collapsible sidebar drawer. Container padding: `p-4`.
- **Tablet (`640px – 1023px`)**: 2-column cards, modal dialogs centered with backdrop blur. Container padding: `p-6`.
- **Desktop (`>= 1024px`)**: Fixed 256px sidebar, 3 or 4-column cards, multi-pane detail views. Container padding: `p-8`.

### 4.2 Application Shell
- **Sidebar ([Sidebar.jsx](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/frontend/src/components/layout/Sidebar.jsx))**:
  - Desktop: Persistent `w-64 border-r bg-card p-5`.
  - Mobile: Full height slide-over modal drawer (`w-72 max-w-[80vw]`) with backdrop overlay and close (`X`) button.
  - Active Item: `bg-primary text-primary-foreground shadow-sm aria-current="page"`.
- **Topbar ([Topbar.jsx](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/frontend/src/components/layout/Topbar.jsx))**:
  - Fixed height `h-16`, flex layout, border-bottom.
  - Left: Mobile hamburger menu button (`md:hidden`), active route heading, descriptive subtitle (`hidden sm:block`).
  - Right: Search input (`hidden sm:flex`), notification bell icon, user avatar badge (`D`).

---

## 5. Component Patterns

### 5.1 Modal Dialogs ([ResearchForm.jsx](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/frontend/src/features/research/components/ResearchForm.jsx), [DeleteResearchDialog.jsx](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/frontend/src/features/research/components/DeleteResearchDialog.jsx))
- **Backdrop**: Fixed overlay with `bg-background/80 backdrop-blur-sm`.
- **Card**: Rounded corners (`rounded-2xl`), subtle border, strong shadow (`shadow-2xl`), scrollable maxHeight (`max-h-[92vh] overflow-y-auto`).
- **Keyboard Handling**: Pressing `Escape` invokes `onCancel()`.
- **Accessibility**: `role="dialog" aria-modal="true" aria-labelledby="..."`.

### 5.2 Forms
- **Labels**: Capitalized uppercase sub-labels (`text-xs font-bold uppercase tracking-wider text-foreground`) linked to inputs via `htmlFor`.
- **Required Indicators**: Red asterisk `<span className="text-destructive">*</span>`.
- **Character Counters**: Live counter (`currentLength/maxLength`) aligned to the right of each label.
- **Validation Errors**: Inline messages rendered in `text-xs font-medium text-destructive`. Input border transitions to `border-destructive focus:ring-destructive/20`.
- **Buttons**:
  - Submit: `bg-primary text-primary-foreground hover:opacity-90 active:scale-95 disabled:opacity-50`.
  - Cancel: `border bg-background text-foreground hover:bg-muted`.

### 5.3 Empty & Feedback States
- **Database Empty**: Dotted border card (`border-dashed bg-card p-8 sm:p-14 text-center`) with `FolderKanban` icon and direct primary action button.
- **Search Empty**: Clean illustration with `SearchX` icon and "Reset Filters" action.
- **Success Notification**: Top-anchored green banner (`border-emerald-500/20 bg-emerald-500/10 text-emerald-800`) with check icon, auto-dismissing after 4000ms.
- **Error Notification**: Top-anchored red banner (`border-destructive/20 bg-destructive/10 text-destructive`) with alert icon.

---

## 6. Accessibility & Keyboard Guidelines

- **Focus Ring**: All interactive inputs, buttons, and select elements must feature a clear outline focus ring (`focus:ring-2 focus:ring-ring/20 outline-none`).
- **Contrast Compliance**: Normal text must exceed 4.5:1 contrast; large text/headings must exceed 3:1. Bharmafills headings achieve >16:1 against background cards.
- **Semantic HTML**: All navigational lists use `<nav aria-label="...">` and `<button aria-current="page">`.
- **Icon Buttons**: Icon-only buttons must provide explicit `aria-label` and `title` attributes.

---

## 7. Cross-References

- For implemented features, see [PRD.md](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/PRD.md).
- For software architecture and component hierarchy, see [ARCHITECTURE.md](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/ARCHITECTURE.md).
- For automated UI testing procedures, see [docs/TESTING.md](file:///d:/Users/Vikas%20Salunke/Downloads/Shinchan/docs/TESTING.md).
