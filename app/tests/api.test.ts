import { AbortedError, ApiError } from "../src/core/api";
import { GameEvent } from "../src/core/events";
import { FakeTransport, apiWith, sse, turn } from "./helpers";

async function collect(gen: AsyncGenerator<GameEvent>): Promise<GameEvent[]> {
  const out: GameEvent[] = [];
  for await (const e of gen) out.push(e);
  return out;
}

describe("streamChat", () => {
  test("yields typed events from a stream that arrives in odd chunks", async () => {
    const t = new FakeTransport();
    t.streamBody = turn("The door splinters.");
    const events = await collect(apiWith(t).streamChat("I kick it"));
    expect(events.map((e) => e.type)).toEqual(["message_start", "text", "message_end"]);
    expect((events[1] as { delta: string }).delta).toBe("The door splinters.");
    expect(t.calls[0]).toMatchObject({ url: "http://x/chat", body: { message: "I kick it", session_id: "default" } });
  });

  test("a stream that ends without a terminal event ends with an error event", async () => {
    const t = new FakeTransport();
    t.streamBody = sse(["text", { delta: "half" }]);
    const events = await collect(apiWith(t).streamChat("x"));
    expect(events[events.length - 1]).toMatchObject({ type: "error", code: "connection_closed" });
  });

  test("a rejected request throws the server's error", async () => {
    const t = new FakeTransport();
    t.streamStatus = 409;
    t.streamBody = JSON.stringify({ error: { code: "conflict", message: "busy" } });
    await expect(collect(apiWith(t).streamChat("x"))).rejects.toMatchObject({ code: "conflict", status: 409 });
  });

  test("a connection failure becomes an error event", async () => {
    const t = new FakeTransport();
    t.stream = async () => ({ status: 0, error: "network down" });
    const events = await collect(apiWith(t).streamChat("x"));
    expect(events).toEqual([expect.objectContaining({ type: "error", code: "connection_error" })]);
  });

  test("aborting stops the stream and throws AbortedError", async () => {
    const t = new FakeTransport();
    t.streamBody = sse(["message_start", {}], ["text", { delta: "a" }]);
    t.hang = true;
    const ac = new AbortController();
    const gen = apiWith(t).streamChat("x", ac.signal);
    const seen: string[] = [];
    const run = (async () => {
      for await (const e of gen) {
        seen.push(e.type);
        if (e.type === "text") ac.abort();
      }
    })();
    await expect(run).rejects.toBeInstanceOf(AbortedError);
    expect(seen).toEqual(["message_start", "text"]);
  });
});

describe("requests", () => {
  test("errors from the server are mapped", async () => {
    const t = new FakeTransport(() => ({ status: 404, body: { error: { code: "not_found", message: "No such save" } } }));
    await expect(apiWith(t).historyInfo("zz")).rejects.toMatchObject({ code: "not_found", message: "No such save" });
  });
  test("a thrown transport error is a connection error", async () => {
    const t = new FakeTransport(() => {
      throw new Error("boom");
    });
    await expect(apiWith(t).health()).rejects.toMatchObject({ code: "connection_error" });
    await expect(apiWith(t).health()).rejects.toBeInstanceOf(ApiError);
  });
  test("query strings carry the session, and empty values are dropped", async () => {
    const t = new FakeTransport();
    const api = apiWith(t);
    await api.compendiumList("locations", "", "", "tree");
    await api.save("a b", true);
    await api.character("Kit Harrow");
    expect(t.calls.map((c) => c.url)).toEqual([
      "http://x/compendium/locations?session_id=default&sort=tree",
      "http://x/history/a%20b/save?session_id=default&overwrite=true",
      "http://x/characters/Kit%20Harrow?session_id=default",
    ]);
  });
});
