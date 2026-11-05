import { Page, expect, test } from "@playwright/test";

const SERVER = "http://127.0.0.1:8765";

async function say(page: Page, text: string) {
  await page.getByTestId("input").fill(text);
  await page.getByTestId("input").press("Enter");
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

test("the side pane shows the status and the details beside the story", async ({ page }) => {
  await open(page);
  await say(page, "begin");
  await expect(page.getByTestId("status-meta")).toContainText("Adventure", { timeout: 15_000 });
  await say(page, "establish Wren");
  await expect(page.getByTestId("status-note")).toHaveText("", { timeout: 15_000 });

  // two panes side by side: the story and the reply on the left, the status above the details on the right
  await expect(page.getByTestId("nav-status")).toHaveCount(0);
  const right = (await page.getByTestId("right-pane").boundingBox())!;
  const story = (await page.getByTestId("transcript").boundingBox())!;
  const input = (await page.getByTestId("input").boundingBox())!;
  expect(right.x).toBeGreaterThan(story.x + story.width - 2);
  expect(right.width).toBeGreaterThanOrEqual(360);
  expect(right.width).toBeLessThanOrEqual(560);
  expect(input.height).toBeGreaterThanOrEqual(200); // three times as tall as it was
  expect(input.x + input.width).toBeLessThanOrEqual(right.x + 1); // the reply field is in the left pane
  const top = (await page.getByTestId("status-pane").boundingBox())!;
  const bottom = (await page.getByTestId("details-pane").boundingBox())!;
  expect(bottom.y).toBeGreaterThanOrEqual(top.y + top.height - 1);
  expect(Math.abs(top.width - bottom.width)).toBeLessThan(2);

  // the status: the place with its picture, then the party; the details start with the place
  const status = page.getByTestId("status-section");
  await expect(status).not.toContainText("Loading");
  const view = status.getByTestId("view");
  await expect(view).toBeVisible({ timeout: 20_000 });
  expect(await view.locator("img").getAttribute("src")).toContain("/portraits/p_");
  expect(await view.locator("img").evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0)).toBe(true);
  const box = (await view.boundingBox())!;
  expect(box.width / box.height).toBeCloseTo(1.5, 1); // landscape, 3:2
  expect(box.height).toBeLessThan(top.height);
  await expect(page.getByTestId("party-Test Hero")).toBeVisible();
  const here = status.getByTestId("status-here"); // the people present, under the party
  await expect(here).toContainText("Innkeeper");
  await page.getByTestId("here-Innkeeper").click(); // a person: their compendium entry in the details
  await expect(page.getByTestId("details-pane").getByTestId("compendium-detail")).toContainText("Innkeeper");
  await expect(page.getByTestId("details-pane").getByTestId("tab-characters")).toHaveCount(0); // just the entry
  await page.screenshot({ path: "e2e/shots/status-npc.png" });
  await page.getByTestId("status-place").click();
  await expect(page.getByTestId("details-pane").getByTestId("compendium-detail")).toHaveCount(0);
  expect((await here.boundingBox())!.y).toBeGreaterThan((await page.getByTestId("party-Test Hero").boundingBox())!.y);
  // the details do not repeat the name or the picture of the place, which the status already shows
  await expect(page.getByTestId("details")).not.toContainText("Day 1, 18:00");
  await expect(page.getByTestId("details")).not.toContainText("Everyone here");
  await expect(page.getByTestId("details")).toContainText("Here");
  await expect(page.getByTestId("details").getByTestId("view")).toHaveCount(0);
  await page.screenshot({ path: "e2e/shots/status-open.png" });

  // a character: the sheet with the portrait the server made, or the placeholder while it is painted
  await page.getByTestId("party-Test Hero").click();
  await expect(page.getByTestId("details")).toContainText("Test Hero");
  const portrait = page.getByTestId("details").getByTestId("portrait");
  await expect(portrait).toBeVisible({ timeout: 20_000 });
  const img = portrait.locator("img");
  expect(await img.getAttribute("src")).toContain("/portraits/p_");
  expect(await img.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0)).toBe(true);
  await page.screenshot({ path: "e2e/shots/status-portrait.png" });
  await page.getByTestId("status-place").click(); // the place again
  await expect(page.getByTestId("details").getByTestId("portrait")).toHaveCount(0);

  // the player keeps playing; slash commands move the details
  await say(page, "echo still playing");
  await expect(page.getByTestId("transcript")).toContainText("still playing");
  await say(page, "/sheet hero");
  await expect(page.getByTestId("details")).toContainText("Test Hero");
  await say(page, "/status");
  await expect(page.getByTestId("details").getByTestId("portrait")).toHaveCount(0);

  await say(page, "item Sluice Key acquired"); // the party gets a key item
  await expect(page.getByTestId("transcript")).toContainText("now in the party's hands");
  await page.getByTestId("nav-compendium").click();
  await expect(page.getByTestId("compendium-view")).toBeVisible();
  // the Compendium takes the whole right pane: no status, the list above the detail
  await expect(page.getByTestId("status-section")).toHaveCount(0);
  const comp = (await page.getByTestId("side-pane").boundingBox())!;
  expect(Math.abs(comp.x - right.x)).toBeLessThan(2);
  await expect(page.getByTestId("tab-locations")).toBeVisible();
  await expect(page.getByTestId("tab-hidden")).toBeVisible(); // a debug server
  await expect(page.getByTestId("tab-items")).toBeVisible(); // key items, empty until the party learns of one
  await expect(page.locator('[data-testid^="entry-"]').first()).toBeVisible();
  await page.locator('[data-testid^="entry-"]').first().click();
  await expect(page.getByTestId("compendium-detail")).toBeVisible();
  const list = (await page.getByTestId("compendium-list").boundingBox())!;
  const detail = (await page.getByTestId("compendium-detail").boundingBox())!;
  expect(detail.y).toBeGreaterThan(list.y + list.height - 2);
  await page.screenshot({ path: "e2e/shots/compendium-open.png" });

  // a place's entry shows its view, wide, with the View text under it
  await page.getByTestId("tab-locations").click();
  await page.locator('[data-testid^="entry-"]', { hasText: "Rusty Flagon" }).first().click(); // The Test Marches has no look
  const placeView = page.getByTestId("compendium-detail").getByTestId("view");
  await expect(placeView).toBeVisible({ timeout: 20_000 });
  expect(await placeView.locator("img").evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0)).toBe(true);
  await expect(page.getByTestId("compendium-detail")).toContainText("View");
  await page.screenshot({ path: "e2e/shots/compendium-view.png" });

  // a person's entry shows the portrait made for them
  await page.getByTestId("tab-characters").click();
  await page.locator('[data-testid^="entry-"]').first().click();
  const npc = page.getByTestId("compendium-detail").getByTestId("portrait");
  await expect(npc).toBeVisible({ timeout: 20_000 });
  expect(await npc.locator("img").getAttribute("src")).toContain("/portraits/p_");
  expect(await npc.locator("img").evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0)).toBe(true);
  await page.screenshot({ path: "e2e/shots/compendium-portrait.png" });

  // a key item the party holds: its standing, its description and a picture in the shape its description chose
  await page.getByTestId("tab-items").click();
  await page.locator('[data-testid^="entry-"]', { hasText: "Sluice Key" }).first().click();
  const itemPage = page.getByTestId("compendium-detail");
  await expect(itemPage).toContainText("Held by the party since turn");
  const itemPicture = itemPage.locator('[data-testid="portrait"], [data-testid="view"]');
  await expect(itemPicture).toBeVisible({ timeout: 20_000 });
  expect(await itemPicture.locator("img").evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0)).toBe(true);
  await expect(itemPage).toContainText("Description");
  await page.screenshot({ path: "e2e/shots/compendium-item.png" });

  await page.getByTestId("dock-close").click(); // back to the status and the place
  await expect(page.getByTestId("compendium-view")).toHaveCount(0);
  await expect(page.getByTestId("status-section")).toBeVisible();
  await page.screenshot({ path: "e2e/shots/closed.png" });
  await page.keyboard.press("Escape"); // Esc closes the Compendium too
  await page.getByTestId("nav-compendium").click();
  await expect(page.getByTestId("compendium-view")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("compendium-view")).toHaveCount(0);

  // a narrow window is one column: the side pane above the story, and it can be hidden
  await page.setViewportSize({ width: 800, height: 900 });
  await expect(page.getByTestId("side-toggle")).toBeVisible();
  const narrow = (await page.getByTestId("right-pane").boundingBox())!;
  const narrowStory = (await page.getByTestId("transcript").boundingBox())!;
  expect(narrow.y).toBeLessThan(narrowStory.y);
  await page.getByTestId("side-toggle").click();
  await expect(page.getByTestId("right-pane")).toHaveCount(0);
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
