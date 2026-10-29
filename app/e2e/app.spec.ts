import { Page, expect, test } from "@playwright/test";

const SERVER = "http://127.0.0.1:8765";

async function say(page: Page, text: string) {
  await page.getByTestId("input").fill(text);
  await page.getByTestId("send").click();
}

async function open(page: Page) {
  await page.goto(`/?server=${encodeURIComponent(SERVER)}&session=e2e`);
  await expect(page.getByText("Welcome! This is Session 0")).toBeVisible();
}

test.beforeEach(async ({ request }) => {
  await request.post(`${SERVER}/chat/new?session_id=e2e`);
});

test("a turn streams in, with formatting and dice", async ({ page }) => {
  await open(page);
  await expect(page.getByTestId("status-meta")).toContainText("connected");
  await say(page, "markdown");
  await expect(page.getByText("You: markdown")).toBeVisible();
  await expect(page.getByTestId("transcript")).toContainText("The Sunken Temple");
  await expect(page.getByTestId("status-note")).toHaveText("");
  await page.screenshot({ path: "e2e/shots/markdown.png" });
  await say(page, "roll 1d20+5 # attack");
  await expect(page.getByTestId("transcript")).toContainText("1d20+5");
  await expect(page.getByTestId("transcript")).toContainText("# attack");
  // the input is free again when the turn ended
  await expect(page.getByTestId("status-note")).toHaveText("");
});

test("Enter sends and Shift+Enter adds a line", async ({ page }) => {
  await open(page);
  const input = page.getByTestId("input");
  await input.click();
  await page.keyboard.type("line one");
  await page.keyboard.press("Shift+Enter");
  await page.keyboard.type("line two");
  await expect(input).toHaveValue("line one\nline two");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("transcript")).toContainText("You: line one");
  await expect(input).toHaveValue("");
});

test("the tabs share the screen with the story", async ({ page }) => {
  await open(page);
  await say(page, "begin");
  await expect(page.getByTestId("status-meta")).toContainText("Adventure", { timeout: 15_000 });
  await say(page, "establish Wren");
  await expect(page.getByTestId("status-note")).toHaveText("", { timeout: 15_000 });

  const story = await page.getByTestId("transcript").boundingBox();
  await page.getByTestId("nav-status").click();
  const dock = page.getByTestId("dock");
  await expect(dock).toBeVisible();
  await expect(page.getByTestId("status-view")).toBeVisible();
  await expect(page.getByTestId("status-view")).not.toContainText("Loading");
  const d = (await dock.boundingBox())!;
  const t = (await page.getByTestId("transcript").boundingBox())!;
  // the open tab takes the upper half of the story area and the story keeps the lower half
  expect(Math.abs(d.height - t.height)).toBeLessThan(40);
  expect(d.y).toBeLessThan(t.y);
  expect(t.height).toBeLessThan(story!.height);
  await page.screenshot({ path: "e2e/shots/status-open.png" });

  // the party member's tab shows the portrait the server made for them, or the placeholder while it is painted
  await page.getByTestId("tab-c:Test Hero").click();
  await expect(page.getByTestId("status-view")).toContainText("Test Hero");
  const portrait = page.getByTestId("portrait");
  await expect(portrait).toBeVisible({ timeout: 20_000 });
  const img = portrait.locator("img");
  expect(await img.getAttribute("src")).toContain("/portraits/p_");
  expect(await img.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0)).toBe(true);
  await page.screenshot({ path: "e2e/shots/status-portrait.png" });
  await page.getByTestId("tab-status").click();

  // the player can keep playing with the tab open
  await say(page, "echo still playing");
  await expect(page.getByTestId("transcript")).toContainText("still playing");
  await expect(dock).toBeVisible();

  await page.getByTestId("nav-compendium").click();
  await expect(page.getByTestId("compendium-view")).toBeVisible();
  await expect(page.getByTestId("tab-locations")).toBeVisible();
  await expect(page.getByTestId("tab-hidden")).toBeVisible(); // a debug server
  await expect(page.locator('[data-testid^="entry-"]').first()).toBeVisible();
  await page.locator('[data-testid^="entry-"]').first().click();
  await expect(page.getByTestId("compendium-detail")).toBeVisible();
  await page.screenshot({ path: "e2e/shots/compendium-open.png" });

  // a person's entry shows the portrait made for them
  await page.getByTestId("tab-characters").click();
  await page.locator('[data-testid^="entry-"]').first().click();
  const npc = page.getByTestId("compendium-detail").getByTestId("portrait");
  await expect(npc).toBeVisible({ timeout: 20_000 });
  expect(await npc.locator("img").getAttribute("src")).toContain("/portraits/p_");
  expect(await npc.locator("img").evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0)).toBe(true);
  await page.screenshot({ path: "e2e/shots/compendium-portrait.png" });

  await page.getByTestId("dock-close").click();
  await expect(dock).toBeHidden();
  await page.screenshot({ path: "e2e/shots/closed.png" });
});

test("save, load and new game", async ({ page }) => {
  await open(page);
  await say(page, "echo remember this");
  await expect(page.getByTestId("transcript")).toContainText("remember this");
  await page.getByTestId("nav-save").click();
  await page.getByTestId("save-name").fill("e2e-save");
  await page.getByTestId("dialog-ok").click();
  await expect(page.getByTestId("transcript")).toContainText("Saved as 'e2e-save'");
  await expect(page.getByTestId("status-meta")).toContainText("e2e-save");

  // the very same file is visible to the server's own list (and so to the terminal client)
  const list = await (await page.request.get(`${SERVER}/history`)).json();
  expect(list.histories.map((h: { name: string }) => h.name)).toContain("e2e-save");

  await page.getByTestId("nav-new").click();
  await page.getByTestId("dialog-ok").click(); // the game was saved, so this is a plain confirmation
  await expect(page.getByText("New game started")).toBeVisible();
  await expect(page.getByTestId("transcript")).not.toContainText("remember this");

  await page.getByTestId("nav-load").click();
  await page.getByTestId("save-e2e-save").click();
  await page.getByTestId("dialog-ok").click();
  await expect(page.getByTestId("transcript")).toContainText("remember this");
  await expect(page.getByTestId("transcript")).toContainText("Loaded 'e2e-save'");
});

test("slash commands and unknown commands", async ({ page }) => {
  await open(page);
  await say(page, "/help");
  await expect(page.getByTestId("transcript")).toContainText("/compendium [TAB|NAME]");
  await say(page, "/bogus");
  await expect(page.getByTestId("transcript")).toContainText("Unknown command: /bogus");
  await say(page, "/saves");
  await expect(page.getByTestId("transcript")).toContainText(/No saved games|messages/);
});

test("Escape cancels a running turn", async ({ page }) => {
  await open(page);
  await say(page, "slow");
  await expect(page.getByTestId("stop")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("transcript")).toContainText("interrupted");
});

test("the story follows new text, unless the player has scrolled up", async ({ page }) => {
  await open(page);
  const atBottom = () =>
    page.getByTestId("transcript").evaluate((el) => el.scrollHeight - (el.scrollTop + el.clientHeight) < 8);
  await say(page, "long 14");
  await expect(page.getByTestId("status-note")).toHaveText("", { timeout: 15_000 });
  await expect(page.getByTestId("transcript")).toContainText("first text");
  await expect.poll(atBottom).toBe(true);

  await page.getByTestId("transcript").evaluate((el) => (el.scrollTop = 0));
  await page.waitForTimeout(150);
  await say(page, "slow");
  await expect(page.getByTestId("transcript")).toContainText("You: slow");
  // a new message from the player brings the view back to the bottom
  await expect.poll(atBottom).toBe(true);
});
