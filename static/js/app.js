/**
 * Client-side "sprinkles" for Compassion Letter Lab.
 *
 * Alpine.js components are registered on the `alpine:init` event, which Alpine
 * fires before it walks the DOM. This file is loaded (deferred) BEFORE the
 * Alpine bundle, so the listener is attached in time.
 *
 * We use Alpine's CSP build: attribute expressions are limited to a small, safe
 * subset (identifiers, member access, comparison, logical, ternary, string
 * concat) and `eval()` is never used. So all real logic lives in the component
 * methods below (plain JS) and the markup only references them by name
 * (e.g. `x-on:input="check"`, `x-bind:disabled="!valid"`).
 */

document.addEventListener("alpine:init", () => {
  /**
   * Start-page form gate. Disables the submit button until the participant has
   * entered both names and ticked at least TWO languages they speak.
   *
   * Bound in templates/start.html with `x-data="startForm"` on the <form>, so
   * `this.$el` is the form element. It only READS the form state — the inputs
   * stay plain server-rendered HTML, which keeps the server's values (including
   * those re-rendered after a rejected submit) authoritative.
   */
  window.Alpine.data("startForm", () => ({
    /** @type {boolean} whether every required field is satisfied */
    valid: false,

    /** Recompute {@link valid} from the current form state. */
    check() {
      const form = /** @type {HTMLFormElement} */ (this.$el);
      const named =
        form.first_name.value.trim() !== "" &&
        form.last_name.value.trim() !== "";
      const spoken =
        form.querySelectorAll('input[name="spoken_langs"]:checked').length;
      this.valid = named && spoken >= 2;
    },

    /** Alpine lifecycle hook — seed {@link valid} from the initial markup. */
    init() {
      this.check();
    },
  }));

  /**
   * "My languages" edit-form gate. Same minimum-two rule as the start page, but
   * with no name fields. Bound in templates/languages.html. Server-side
   * validation stays authoritative; with JS off the Save button is always enabled.
   */
  window.Alpine.data("languagesForm", () => ({
    /** @type {boolean} whether at least two languages are ticked */
    valid: false,

    /** Recompute {@link valid} from the current selection. */
    check() {
      const form = /** @type {HTMLFormElement} */ (this.$el);
      this.valid =
        form.querySelectorAll('input[name="spoken_langs"]:checked').length >= 2;
    },

    /** Alpine lifecycle hook — seed {@link valid} from the initial markup. */
    init() {
      this.check();
    },
  }));

  /**
   * Evaluation-page form. Tracks two things, both progressive enhancements over
   * server-rendered HTML (the server stays authoritative; with JS off everything
   * still works):
   *
   *  - the missed-issue yes/no answer, so the category + reason fields reveal
   *    (x-show) and become required (x-bind:required) only when "Yes" is chosen;
   *  - the preference answer, so the comment box's placeholder adapts to the
   *    choice (a plain `placeholder=` attribute supplies a sensible default when
   *    JS is off).
   *
   * It also holds the one-time welcome card's dismissed state. The card is only
   * rendered on a volunteer's first letter; dismissing it hides it client-side
   * and remembers that for the rest of the browser session, so reloading the
   * first letter before voting does not reshow it.
   */
  window.Alpine.data("evalForm", () => ({
    /** Session-storage key remembering that the welcome card was dismissed. */
    WELCOME_KEY: "welcome_dismissed",

    /** @type {string} the selected missed_yes_no value ('' until answered) */
    missed: "",

    /** @type {string} the selected preference value ('' until chosen) */
    preference: "",

    /** @type {boolean} whether the welcome card has been dismissed this session */
    welcomeDismissed: false,

    /** Whether "Yes" is selected — drives the reveal + the fields' required state. */
    get missedYes() {
      return this.missed === "yes";
    },

    /** Placeholder for the preference comment, matched to the current choice. */
    get preferenceCommentPlaceholder() {
      if (this.preference === "A" || this.preference === "B") {
        return "Why did you prefer this one? Your answer helps us improve the AI.";
      }
      if (this.preference === "Equivalent") {
        return "Optional, what made them equally good?";
      }
      return "Tell us why, it helps us improve the AI.";
    },

    /** Hide the welcome card and remember the choice for this browser session. */
    dismissWelcome() {
      this.welcomeDismissed = true;
      try {
        window.sessionStorage.setItem(this.WELCOME_KEY, "1");
      } catch (e) {
        /* sessionStorage unavailable (private mode, etc.) — dismiss is still in effect for this view */
      }
    },

    /** Alpine lifecycle hook — restore the dismissed state from this session. */
    init() {
      try {
        this.welcomeDismissed = window.sessionStorage.getItem(this.WELCOME_KEY) === "1";
      } catch (e) {
        /* sessionStorage unavailable — leave the card shown */
      }
    },
  }));
});
