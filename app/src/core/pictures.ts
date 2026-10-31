/** How big a picture's frame is, by its shape (docs/KEY_ITEMS.md 8, docs/PLACES.md 10). Pure, so it is tested without
 * a screen: the component only draws what this says. */

export type Shape = "square" | "landscape" | "portrait";

/** The shape the server named; anything unknown is square. */
export function shapeOf(picture: unknown): Shape {
  const shape = (picture as { shape?: unknown } | null | undefined)?.shape;
  return shape === "landscape" || shape === "portrait" ? shape : "square";
}

export interface FrameInput {
  shape: Shape;
  windowWidth: number;
  windowHeight: number;
  /** The widest a landscape picture may be; it is narrower where the column is. */
  maxWidth: number;
  /** Also keep a landscape picture to about a third of the window's height, so what is under it stays in view. */
  fitHeight: boolean;
}

/** A landscape picture fills its column up to a width and keeps 3:2; the others have a fixed size. */
export type Frame = { fill: true; maxWidth: number; aspectRatio: number } | { fill: false; width: number; height: number };

export function frameFor({ shape, windowWidth, windowHeight, maxWidth, fitHeight }: FrameInput): Frame {
  const small = windowWidth < 600;
  if (shape === "landscape") {
    return { fill: true, maxWidth: fitHeight ? Math.min(maxWidth, Math.round(windowHeight * 0.3 * 1.5)) : maxWidth, aspectRatio: 3 / 2 };
  }
  if (shape === "portrait") return small ? { fill: false, width: 160, height: 240 } : { fill: false, width: 240, height: 360 };
  return small ? { fill: false, width: 120, height: 120 } : { fill: false, width: 160, height: 160 };
}

/** What a picture that is being painted says, by what it is a picture of. */
export function paintingText(subject: string | undefined, shape: Shape): string {
  if (subject === "item") return "Painting an object…";
  return shape === "landscape" ? "Painting a view…" : "Painting a portrait…";
}
