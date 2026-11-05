import { hpTone, shortHeadline } from "../src/core/party";

test("a headline is cut to the class and level", () => {
  expect(shortHeadline("Human Paladin 3 (Oath of the Ancients)")).toBe("Paladin 3");
  expect(shortHeadline("Dwarf Druid 3 (Circle of the Land, Mountain)")).toBe("Druid 3");
  expect(shortHeadline("A wandering bard")).toBe("A wandering bard");
  expect(shortHeadline(undefined)).toBe("");
});

test("hit points are tinted by how much is left", () => {
  expect(hpTone("22/25")).toBe("ok");
  expect(hpTone("13/25")).toBe("ok");
  expect(hpTone("12/25")).toBe("low");
  expect(hpTone("6/25")).toBe("critical");
  expect(hpTone("0/25")).toBe("critical");
  expect(hpTone("-")).toBe("unknown");
  expect(hpTone(undefined)).toBe("unknown");
});
