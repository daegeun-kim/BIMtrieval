// Persistent disclosure (spec_v013 §6.4).
//
// Not dismissable, and deliberately not styled as a cookie bar people learn to
// swat away. A visitor must be able to tell at any moment that the answers on
// screen are recordings, not a live system responding to them.
//
// It docks directly above the application's status readout — the card that
// carries the Fine / Standard / Fast quality control — and matches its width, so
// the two read as one stack in the bottom-left corner rather than as a demo
// element competing with the real UI.
//
// That width is measured rather than assumed: `.readout` sizes to its content
// (the model name) under a `44vw` cap, so any hardcoded number would be wrong
// for some model or some viewport. This element is a sibling of `.app` and
// cannot inherit the layout variables inside it, so measurement is also the only
// way to line the two up.
//
// An earlier version of this card was placed over the readout instead of above
// it, which hid the quality control completely (§14.8) — hence `demo.spec.ts`
// clicks that control.
import { useEffect, useState } from "react";

/** Gap between the readout and this card, matching the app's own 12 px rhythm. */
const GAP_PX = 12;

interface Dock {
  left: number;
  width: number;
  bottom: number;
}

/**
 * Below this, a `.readout` measurement is not a real one.
 *
 * Crossing the mobile breakpoint reflows that card — the media query hides its
 * text lines and the remaining controls re-wrap — and a measurement taken mid
 * reflow can catch it a few dozen pixels wide. Caching such a value docked the
 * banner at 34 px wide and 1200 px tall, off the top of the screen. Rotating a
 * phone is enough to reach it.
 */
const MIN_PLAUSIBLE_WIDTH_PX = 80;

function readDock(): Dock | null {
  const readout = document.querySelector<HTMLElement>(".readout");
  if (!readout) return null;
  const rect = readout.getBoundingClientRect();
  if (rect.width < MIN_PLAUSIBLE_WIDTH_PX || rect.height === 0) return null;
  return {
    left: Math.round(rect.left),
    width: Math.round(rect.width),
    bottom: Math.round(window.innerHeight - rect.top + GAP_PX),
  };
}

function same(a: Dock | null, b: Dock | null): boolean {
  if (a === null || b === null) return a === b;
  return a.left === b.left && a.width === b.width && a.bottom === b.bottom;
}

export default function DemoBanner() {
  const [dock, setDock] = useState<Dock | null>(null);

  useEffect(() => {
    // Only ever writes state when a number actually changed. The mutation
    // observer below watches the whole document, so an unconditional setState
    // here would re-render, mutate, and measure again without end.
    let current: Dock | null = null;
    let frame = 0;
    let settle = 0;

    const measure = () => {
      const next = readDock();
      if (next === null || same(current, next)) return;
      current = next;
      setDock(next);
    };

    // Always measured on the next frame, never synchronously inside the event
    // that triggered it: a resize handler runs before the layout it caused has
    // settled, and the value read there can be a snapshot of a card mid-reflow.
    const scheduleMeasure = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    };

    // A breakpoint crossing reflows over more than one frame — the media query
    // switches, the readout re-wraps, fonts settle — so a resize also gets a
    // late second look. Cheap, and it is the difference between docking against
    // the final layout and docking against a moment inside the transition.
    const onResize = () => {
      scheduleMeasure();
      clearTimeout(settle);
      settle = window.setTimeout(measure, 250);
    };

    measure();
    window.addEventListener("resize", onResize);

    // The readout renders with the model, so it does not exist on first paint —
    // and React can replace the node afterwards, which silently orphans a
    // ResizeObserver pointed at the old one. So both observers stay live for the
    // life of the page: the mutation observer re-attaches whenever the node is
    // swapped, and the resize observer catches it growing in place as the model
    // name and the quality control fill it out.
    //
    // An earlier version connected the mutation observer only when the readout
    // was missing at mount, then stopped. The card docked once against a
    // half-rendered readout and kept those numbers, ending up narrower than the
    // card it was supposed to match and overlapping it by 33 px.
    const resizeObserver = new ResizeObserver(scheduleMeasure);
    let observed: Element | null = null;
    const attach = () => {
      const readout = document.querySelector(".readout");
      if (!readout || readout === observed) return;
      if (observed) resizeObserver.unobserve(observed);
      resizeObserver.observe(readout);
      observed = readout;
    };

    const mutationObserver = new MutationObserver(() => {
      attach();
      scheduleMeasure();
    });
    attach();
    mutationObserver.observe(document.body, { childList: true, subtree: true });

    return () => {
      window.removeEventListener("resize", onResize);
      cancelAnimationFrame(frame);
      clearTimeout(settle);
      resizeObserver.disconnect();
      mutationObserver.disconnect();
    };
  }, []);

  return (
    <aside
      className={`demo-banner${dock ? " is-docked" : ""}`}
      role="note"
      style={dock ? { left: dock.left, width: dock.width, bottom: dock.bottom } : undefined}
    >
      <p className="demo-banner-title">Static demo</p>

      {/* Two wordings, one shown at a time by CSS. On a phone the card shares a
          ~390 px band with the viewer, and the full paragraph pushed it to
          228 px — over half the viewer, and on top of the 3D controls. Trimming
          the type alone was not enough; the sentence itself has to be shorter.
          Toggled in CSS rather than JS so it follows a rotation with no state to
          resynchronise. */}
      <p className="demo-banner-body demo-on-wide">
        Real interface, real 3D model, three pre-recorded answers. There is no
        backend, no database, and no API key behind this page — so answers appear
        instantly that really took 6–22 seconds.
      </p>
      <p className="demo-banner-body demo-on-narrow">
        Real interface and 3D model. Three answers recorded in advance — no
        backend, no API key.
      </p>
      <a
        className="demo-banner-link"
        href="https://github.com/daegeun-kim/BIMtrieval"
        target="_blank"
        rel="noreferrer"
      >
        Source, benchmark, and how to run it →
      </a>

      {/* CC BY 4.0 requires attribution to reach the recipient, and a text file
          nobody opens does not achieve that — so the credit is on the page
          itself, not only in ATTRIBUTION.txt (spec_v013 §8.2).

          The narrow variant is shorter but not lighter: title, author, source,
          licence, and the fact of modification are all still named, because
          those are the licence's actual requirements rather than a house
          style. */}
      <p className="demo-attribution demo-on-narrow">
        <em>Schependomlaan</em> by ROOT bv via{" "}
        <a href="https://github.com/buildingSMART/Sample-Test-Files" target="_blank" rel="noreferrer">
          buildingSMART
        </a>{" "}
        &middot;{" "}
        <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer">
          CC BY 4.0
        </a>{" "}
        &middot; converted to Fragments &middot;{" "}
        <a href="ATTRIBUTION.txt" target="_blank" rel="noreferrer">
          notice
        </a>
      </p>

      <p className="demo-attribution demo-on-wide">
        Model: <em>IFC Schependomlaan incl planningsdata</em> by ROOT bv via{" "}
        <a href="https://github.com/buildingSMART/Sample-Test-Files" target="_blank" rel="noreferrer">
          buildingSMART
        </a>
        , licensed{" "}
        <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer">
          CC BY 4.0
        </a>
        . Converted from IFC to Fragments for web rendering —{" "}
        <a href="ATTRIBUTION.txt" target="_blank" rel="noreferrer">
          full notice
        </a>
        .
      </p>
    </aside>
  );
}
