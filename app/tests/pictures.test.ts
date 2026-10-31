import { frameFor, paintingText, shapeOf } from "../src/core/pictures";

const input = { windowWidth: 1200, windowHeight: 800, maxWidth: 360, fitHeight: false };

describe("pictures", () => {
  test("the server's shape is read, and anything else is square", () => {
    expect(shapeOf({ shape: "landscape" })).toBe("landscape");
    expect(shapeOf({ shape: "portrait" })).toBe("portrait");
    expect(shapeOf({ shape: "square" })).toBe("square");
    expect(shapeOf({ shape: "wide" })).toBe("square");
    expect(shapeOf(null)).toBe("square");
    expect(shapeOf(undefined)).toBe("square");
  });
  test("a landscape picture fills the column up to a width, at 3:2", () => {
    expect(frameFor({ ...input, shape: "landscape" })).toEqual({ fill: true, maxWidth: 360, aspectRatio: 1.5 });
    expect(frameFor({ ...input, shape: "landscape", maxWidth: 720, fitHeight: true })).toEqual({ fill: true, maxWidth: 360, aspectRatio: 1.5 });
    expect(frameFor({ ...input, shape: "landscape", maxWidth: 300, fitHeight: true })).toMatchObject({ maxWidth: 300 });
  });
  test("a portrait-shaped picture is two thirds as wide as it is tall, smaller on a phone", () => {
    expect(frameFor({ ...input, shape: "portrait" })).toEqual({ fill: false, width: 240, height: 360 });
    expect(frameFor({ ...input, shape: "portrait", windowWidth: 400 })).toEqual({ fill: false, width: 160, height: 240 });
  });
  test("a square one is a small square", () => {
    expect(frameFor({ ...input, shape: "square" })).toEqual({ fill: false, width: 160, height: 160 });
    expect(frameFor({ ...input, shape: "square", windowWidth: 400 })).toEqual({ fill: false, width: 120, height: 120 });
  });
  test("a picture being painted says what it is of", () => {
    expect(paintingText("item", "portrait")).toBe("Painting an object…");
    expect(paintingText("location", "landscape")).toBe("Painting a view…");
    expect(paintingText("npc", "square")).toBe("Painting a portrait…");
  });
});
