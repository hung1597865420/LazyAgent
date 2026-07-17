"""Shared UI audit criteria for visual and accessibility tools."""

EXECUTIVE_COMMAND_UI_CRITERIA = """
Executive Command UI audit criteria:
- Brand personality: enterprise-grade, precise, trustworthy, efficient; dense information is acceptable only when hierarchy stays clear.
- Palette: Biscay Navy #16315E anchors headers/nav/primary text; Bright Turquoise #10CFC9 is reserved for primary actions, focus, active/progress/positive states; backgrounds use Off-White #F4F5F7/#F8FAFC and surfaces use #FFFFFF.
- Semantic color: red only for high risk/destructive/reject, amber for moderate risk, emerald for success; do not use decorative colors without meaning.
- Typography: Space Grotesk for display/headings; IBM Plex Sans or Inter Tight for body/UI labels; JetBrains Mono/IBM Plex Mono for IDs, numbers, taglines and dense data. Numeric/data UI should use tabular numerals where possible.
- Geometry: business/product UI should prefer 1px borders over heavy shadows; radius is usually 4-8px for cards/buttons, sharp edges are allowed for command/sidebar/header surfaces. Login/auth cards may use 12-16px radius and glass treatment when consistent with the auth spec.
- Layout: desktop command screens should support strong split/mission-control layouts; login/auth screens use two columns on desktop and stack on mobile. Spacing must be intentional, not loose marketing padding inside operational tools.
- Login/auth specifics: support a brand/copy column and login card; floating labels must have accessible labels and preserve enough input padding; submit states must include normal, hover/focus, disabled/loading and error handling.
- Interaction states: every control needs visible hover, focus-visible, active, disabled/loading and error states; focus ring should align with #10CFC9 and pass contrast.
- Responsive: mobile stacks cleanly, touch targets stay at least 44px, text must not overflow cards/buttons, and core actions remain reachable without horizontal scroll.
- Motion: entrance/floating-label/hover motion should be subtle, purposeful and disabled or reduced under prefers-reduced-motion.
- Accessibility: enforce WCAG 2.1 AA contrast, semantic headings, keyboard navigation, form labels, aria only when needed, alt text for meaningful media, visible focus, non-color-only status, and clear error messaging.
- Anti-patterns: flag generic dashboard kits, one-note palettes, low-contrast turquoise text, oversized hero treatment in operational apps, nested cards, decorative clutter, missing state design, and layout that looks pretty but slows repeated work.
""".strip()
