/* Plain-language layer: rule ids -> what's wrong, in words a site owner understands. */

export const PEOPLE = {
  blind: { label: "Blind & screen-reader users", icon: "👂" },
  lowvision: { label: "People with low vision", icon: "👁" },
  keyboard: { label: "Keyboard-only users", icon: "⌨" },
  motor: { label: "People with tremors or limited dexterity", icon: "✋" },
  colorblind: { label: "Colour-blind people", icon: "🎨" },
  cognitive: { label: "People with cognitive or memory disabilities", icon: "🧠" },
  everyone: { label: "Everyone", icon: "👥" },
};

// Who a WCAG success criterion mainly protects.
const WHO_BY_SC = {
  "1.1.1": ["blind"], "1.2.1": ["blind"], "1.2.2": ["everyone"], "1.3.1": ["blind"], "1.3.2": ["blind"],
  "1.3.5": ["cognitive", "motor"], "1.4.1": ["colorblind"], "1.4.3": ["lowvision"], "1.4.4": ["lowvision"],
  "1.4.10": ["lowvision"], "1.4.11": ["lowvision"], "2.1.1": ["keyboard", "blind"], "2.1.2": ["keyboard"],
  "2.2.1": ["cognitive", "motor"], "2.4.1": ["keyboard", "blind"], "2.4.2": ["blind"], "2.4.3": ["keyboard"],
  "2.4.4": ["blind", "cognitive"], "2.4.7": ["keyboard"], "2.5.8": ["motor"], "3.1.1": ["blind"],
  "3.3.1": ["everyone"], "3.3.2": ["cognitive", "everyone"], "4.1.2": ["blind"], "4.1.3": ["blind"],
};

const RULES = {
  "image-alt": ["Images have no text description", "Screen readers announce these images as \"image\" or read out the file name."],
  "alt-text-uninformative": ["Image descriptions are wrong or meaningless", "The alt text is a placeholder, a file name, or describes something else, so screen-reader users get the wrong picture."],
  "informative-image-hidden": ["Important images are hidden from screen readers", "These images carry information but are marked decorative, so screen readers skip them."],
  "color-contrast": ["Text is too faint to read", "The text doesn't stand out enough from its background."],
  "contrast-over-image": ["Text over pictures is hard to read", "Measured from the actual pixels: the background image makes this text too faint."],
  "link-name": ["Links with no name", "Screen readers can only say \"link\"; users can't tell where it goes."],
  "button-name": ["Buttons with no name", "Screen readers can only say \"button\"; users can't tell what it does."],
  "label": ["Form fields without labels", "Screen readers can't say what to type in these fields."],
  "select-name": ["Dropdowns without labels", "Screen readers can't say what these dropdowns are for."],
  "placeholder-as-label": ["Form fields labelled only by grey hint text", "The hint disappears as soon as you type, so you forget what the field was for."],
  "keyboard-inaccessible": ["Clickable things you can't reach with a keyboard", "Parity pressed Tab through the page; these never received focus."],
  "link-purpose-unclear": ["Several links with the same vague text", "\"Read more\" repeated, going to different pages: out of context, users can't tell them apart."],
  "target-size": ["Tap targets too small or too close", "Easy to hit the wrong one, especially on phones or with shaky hands."],
  "html-has-lang": ["Page language not set", "Screen readers may read the page with the wrong accent and pronunciation."],
  "document-title": ["Page has no title", "People using many tabs or a screen reader can't tell what the page is."],
  "frame-title": ["Embedded frames without a title", "Screen readers can't say what the embedded content (e.g. a video) is."],
  "link-in-text-block": ["Links you can only spot by colour", "Links inside text differ from normal text only by colour, which some people can't see."],
  "list": ["Lists that aren't real lists", "Screen readers can't announce how many items there are."],
  "heading-order": ["Headings skip levels", "Screen-reader users navigate by headings; skipped levels make the page structure confusing."],
  "landmark-one-main": ["No main content area marked", "Screen-reader users can't jump straight to the main content."],
  "region": ["Content outside the page's landmark areas", "Screen-reader users who navigate by regions can miss this content."],
  "landmark-unique": ["Page regions with duplicate names", "Screen-reader users can't tell these regions apart."],
  "tabindex": ["Custom tab order", "Positive tabindex values make keyboard focus jump around unpredictably."],
  "aria-required-attr": ["Custom controls missing required information", "E.g. a custom checkbox that never says whether it's checked."],
  "duplicate-id-aria": ["Duplicate IDs used for labels", "Labels may point at the wrong element."],
  "meta-refresh": ["The page refreshes by itself", "Content changes before some people finish reading or filling it in."],
  "frame-tested": ["Embedded content that couldn't be checked", "Parity couldn't look inside these frames; check them by hand."],
  "empty-heading": ["Empty headings", "Screen readers announce a heading with nothing in it."],
  "image-redundant-alt": ["Image descriptions repeat nearby text", "Screen readers read the same words twice."],
};

export function describe(finding) {
  const [title, what] = RULES[finding.rule_id] || [finding.help || finding.rule_id, finding.description || ""];
  const scs = finding.wcag_criteria || [];
  const who = [...new Set(scs.flatMap((sc) => WHO_BY_SC[sc] || []))];
  return { title, what, who: who.length ? who : ["everyone"] };
}

export const CONFIDENCE = {
  "auto-verified": { label: "Confirmed", cls: "b-confirmed", help: "A rule or a measurement proved it." },
  "ai-high-confidence": { label: "AI, high confidence", cls: "b-ai", help: "Found by an AI agent that is at least 80% sure." },
  "needs-review": { label: "Needs a human", cls: "b-review", help: "Parity isn't sure; worth a quick human check." },
};

export const IMPACT = {
  critical: { label: "Critical", cls: "b-critical", rank: 0 },
  serious: { label: "Serious", cls: "b-serious", rank: 1 },
  moderate: { label: "Moderate", cls: "b-moderate", rank: 2 },
  minor: { label: "Minor", cls: "b-minor", rank: 3 },
  unknown: { label: "Unrated", cls: "b-minor", rank: 4 },
};
