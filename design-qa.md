# Design QA

**Source visuals:**

- Spa page: `docs/design-reference.png` (crop of the approved 1586 × 992 mock, starting at x=257 to exclude the Home Assistant sidebar).
- Overview card: `docs/card-design-reference.png` (780 × 447 crop of the approved overview mock).

**Rendered implementation:**

- Spa page: `docs/implementation-desktop.jpg` (1314 × 992 visible content crop of a browser screenshot; browser CSS viewport 1329 × 992, DPR 1; 15 px scrollbar excluded).
- Overview card: `docs/implementation-card.jpg` (800 × 420 app area from an 800 × 450 browser screenshot, DPR 1).
- Same-input comparisons: `docs/design-comparison.png` and `docs/card-design-comparison.png`.

The Spa comparison uses the same desktop density and height. It compares the app area of the mock with the standalone app, since the Home Assistant sidebar belongs to Home Assistant. The mock uses placeholder readings; the browser screenshot uses a 1700 L sample with pH 7.2, alkalinity 100 mg/L, chlorine 0.2 mg/L, the weekly MiniChlor step, and an active cover timer. The card comparison has a valid reading instead of the mock's missing-reading alert.

## Findings

No actionable P0, P1, or P2 differences remain. The page keeps the three-card hierarchy, cyan primary action, orange cover timer, and large touch targets. The five routine buttons include the requested holiday mode, which was absent from the original four-button mock.

- **Typography:** The implementation uses system sans. The mock has slightly broader heading letterforms and larger text in a few places. This is a P3 refinement; the hierarchy and readability remain clear.
- **Spacing and layout:** The final comparison shows the header, three cards, cover banner, and routines at comparable positions. The center card is wider as in the mock. Mobile and a 1000 px iframe width have no horizontal overflow.
- **Colors:** Dark navy surfaces, cyan actions, and orange timer match the approved direction. The card photo is a little darker than the mock, a P3 image treatment difference.
- **Images and icons:** The evening spa photo and product jar are generated assets in the intended style. Material Symbols Rounded provide the UI icons. Their shapes differ slightly from the illustrative mock, a P3 difference.
- **Copy:** Live values replace placeholder text. The cover timer explicitly says it does not mean the water is ready for bathing; this extra line is required by the approved plan.

## Comparison history

1. The first browser comparison showed the cards and timer too high and too short, and the product image resembled a first-aid symbol. I increased the header and card spacing, adjusted the grid proportions and timer height, and replaced the icon with the generated SpaCare-style jar.
2. The next comparison showed the confirmation button smaller and lower than the mock. I increased its height and type size and moved it up within the card. The final `design-comparison.png` is the post-fix evidence.
3. `card-design-comparison.png` confirms the overview card's photo, readings, cover countdown, and Spa action. The timer and measurement status differ because the browser uses live sample data.

## Interaction and responsive checks

- Browser flow: settings, new measurement, +0.2 mg/L chlorine estimate and warning, chemical confirmation, timer, history, weekly routine, and holiday filter/MiniChlor/five-minute wait. The final holiday routine also prompts for a fresh measurement when started; this transition is covered by the automated browser-independent test.
- 1000 × 800 and 390 × 844 CSS viewports: no horizontal overflow; primary controls remain reachable.
- Browser console: no warnings or errors in the tested views.
- A running Home Assistant instance and a physical 10-inch device were not available; the browser viewport checks cover the app layout, not the Home Assistant shell.

**Final result: passed**
