Record what happens to a key item: a quest object the party can get and that helps them in their quest, such as a key, a map or a piece of evidence. Ordinary gear, weapons, coin, supplies and loot are not key items and stay on the character sheets. The test: if the party never had this, would some path of the story stop or change? Only then is it a key item.

Create a key item first with `establish` (`kind: "item"`, with `look_notes` saying what it is and looks like, at most two new key items per call). Name it as the characters would, never in a way that gives its secret away ("the steward's ledger", not "the forged ledger"). A key item you create is not shown to the player until it enters play, so you may create one before the party knows of it. Record what is true about it as facts: `appearance` and `purpose` are shown once the party has it; its contents, origin and powers stay yours until you `reveal` them.

Then use `key_item` for each change, in the same turn as the narration:
- `learned`: the party now knows the item exists but does not have it (a rumor, a map reference, a quest giver's request). The player sees it in their journal as something to find.
- `acquired`: the party has it in hand. It can be called straight away, without `learned` first. Seeing an item or being offered it is not acquiring it. It may also be used when the party gets an item back that they used up or lost.
- `used`: the item has done its job and is gone or spent (a key left in its lock, a letter delivered).
- `lost`: the party no longer has it: stolen, dropped, given away, confiscated or destroyed. Say which in `note`.

Give `note` as one short sentence saying how. Call it in the same response as your other bookkeeping, before your final reply, and write no text beside it.