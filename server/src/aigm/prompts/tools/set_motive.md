Record what a person wants right now, change a motive that play has changed, or note that a hint of one has been shown. Motives are hidden: the player never reads them. They are why a person acts as they do, and they shape which words and offers work on them. The world notes list the motives of the people present, marked GM only; use `recall` for anyone else.

`changes` is a list (at most 6), applied in order, all or nothing:

- `add`: give a recorded person a motive. Use `scope: "scene"` (the default) for what they are after right now, in this place: to get the party out before the boss returns, to impress the captain, to learn who sent them. It lapses when the party leaves or after two hours. Use `scope: "underlying"` only for a lasting want, fear, loyalty, grudge, vice or belief you are inventing for someone who has none. A person can have two lasting motives and one scene motive. Give `text` (one sentence of about 40 words, using names), a `kind` (`want`, `fear`, `loyalty`, `grudge`, `vice` or `belief`) and a `strength`: `leaning` tilts a result, `driven` shapes it. Add `moved_by` (kinds of argument or offer that engage it), `resists` (kinds that bounce off) and `tells` (behavior that hints at it without stating it). You cannot create an `absolute` motive.
- `shift`: a motive has changed because of what happened (a debt cleared, a fear confirmed). Give its `id` and the new `text`, `kind`, `strength` or levers. The old motive is kept as history. A motive marked absolute in your notes never changes, whatever the party does.
- `resolve`: the motive is over. Give its `id` and `outcome`: `satisfied` (they got what they wanted) or `frustrated` (they can no longer have it).
- `disclose`: your narration just showed one of the motive's tells to the player. Give its `id`.

Play every named person from their motives: let the tells show in what they say and do, and never state a motive in narration or dialogue unless the person would say it aloud. Give each person who will speak at length a scene motive before they speak, if they have none. If any change is rejected nothing is recorded, and the error says what to fix.

Call it before the message that holds your final reply, never in that message and never after it. If you are about to roll, roll first, then call this once you have seen the results.

Write no text in the same response as this call: not even a remark such as "I'll record that". Anything you write is shown to the player as story.
