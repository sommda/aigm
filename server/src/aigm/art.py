"""Art styles and the image prompt for character portraits (docs/PORTRAITS.md 5 and 7).

The catalog is data: a style is an id, a name and a written direction that goes into every prompt of a game verbatim,
which is what makes a game's portraits look like a set. A direction describes what the picture is made of and never
names a person, a product or a setting. The prompt is built here, from the style, a fixed framing and the character's
Look and nothing else, so a portrait can show only what the Look says."""

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from aigm.looks import Look
from aigm.rulesets import RULESETS

NO_PORTRAITS = "none"  # the `art_style` value for a game with no portraits
MAX_PROMPT_CHARS = 3200  # well under the model's limit; the tags go first, then the description's tail

# How the people are placed in the picture, the same for every style.
FRAMING = (
    "A tight head-and-shoulders portrait of one character, like an identity portrait: the face fills about half the "
    "height of the picture, the character faces the viewer at a slight angle, centered, with a little room above the "
    "head, and the picture is cropped at the collarbone. Show only the head, neck and tops of the shoulders: do not "
    "show the torso, belt, hands, weapons or anything lower. The background is plain, empty and out of focus, in one "
    "muted tone; ignore any room, place or scene mentioned below. No text, no caption, no border, no frame, no "
    "watermark, no other people."
)


# How a view of a place is placed in the picture, the same for every style (docs/PLACES.md 8.2).
PLACE_FRAMING = (
    "A wide establishing view of one place, in landscape orientation, seen from where a visitor would first stand: the "
    "whole place clear and centered, the horizon level, nothing awkwardly cropped. The place is empty: no people, no "
    "figures and no creatures anywhere in the picture. No text, signs, lettering or writing of any kind. No border, no "
    "frame, no watermark."
)


@dataclass(frozen=True)
class Style:
    id: str
    name: str
    direction: str
    # The direction for a view of a place, where `direction` speaks of faces or characters. Empty: use `direction`.
    place: str = ""

    def direction_for(self, kind: str) -> str:
        return self.place if kind == "place" and self.place else self.direction


STYLES: tuple[Style, ...] = (
    Style(
        "ink", "Pen and ink",
        "Black and white pen-and-ink illustration on white paper, in the manner of a 1970s fantasy rulebook plate: "
        "fine black linework, dense cross-hatching and stippling for shadow, and no color, no gray wash and no tint at "
        "all. Only black ink on white.",
    ),
    Style(
        "gouache", "Classic fantasy painting",
        "A hand-painted 1980s fantasy paperback cover in flat opaque gouache, not photorealistic: matte paint with "
        "visible brush strokes, simplified smooth planes of color, bright saturated hues, strong dark outlines and a "
        "slightly idealized, heroic look.",
        place="A hand-painted 1980s fantasy paperback cover landscape in flat opaque gouache, not photorealistic: matte paint with visible brush strokes, simplified smooth planes of color, bright saturated hues, strong dark outlines and a slightly idealized, adventurous look.",
    ),
    Style(
        "moody", "Moody painting",
        "Dark, painterly fantasy realism from a 1990s campaign sourcebook: visible brushwork, textured paint, muted "
        "earth tones with deep shadows and a few warm highlights, a somber, atmospheric mood.",
    ),
    Style(
        "comic", "Inked and colored",
        "Bold inked fantasy illustration from an early-2000s core rulebook: confident black outlines, flat bright "
        "digital color with simple cel-style shading, dynamic and clearly readable shapes, a slightly comic-book feel.",
    ),
    Style(
        "vivid", "Vivid digital",
        "Stylized digital concept art from the late 2000s, not photorealistic: very high saturation, glossy highlights, "
        "strong colored rim lights in teal and orange, smooth airbrushed gradients, sharp clean edges and slightly "
        "exaggerated heroic proportions.",
        place="Stylized digital fantasy concept art of an environment from the late 2000s, not photorealistic: very high saturation, glossy highlights, strong colored light in teal and orange, smooth airbrushed gradients, sharp clean edges and slightly exaggerated, dramatic scale.",
    ),
    Style(
        "modern", "Modern painting",
        "Contemporary fantasy sourcebook illustration: soft digital painting with clearly visible painterly brush "
        "texture, bright natural daylight, a light airy palette, welcoming grounded mood and gently simplified detail.",
        place="Contemporary fantasy sourcebook environment illustration: soft digital painting with clearly visible painterly brush texture, bright natural daylight, a light airy palette, a welcoming grounded mood and gently simplified detail.",
    ),
    Style(
        "detailed", "Detailed fantasy",
        "Richly detailed fantasy hardback illustration: dense ornament on armor, jewelry and cloth, intricate "
        "textures, dramatic lighting and an epic, polished painted finish with fine edge detail.",
        place="Richly detailed fantasy hardback environment illustration: dense ornament on buildings and ironwork, intricate textures, dramatic lighting and an epic, polished painted finish with fine edge detail.",
    ),
    Style(
        "clean", "Clean stylized",
        "Clean, stylized 2D fantasy illustration, clearly not photorealistic: simplified shapes, smooth flat gradient "
        "shading, a slight vector-art look, a bright harmonious palette, and slightly exaggerated, friendly "
        "proportions and features.",
        place="Clean, stylized 2D fantasy environment illustration, clearly not photorealistic: simplified shapes, smooth flat gradient shading, a slight vector-art look, a bright harmonious palette and slightly exaggerated, friendly proportions.",
    ),
    Style(
        "storybook", "Storybook watercolor",
        "Loose storybook watercolor with ink linework on textured paper: gentle washes of color that bleed softly at "
        "the edges, visible paper grain, a warm and whimsical mood.",
    ),
    Style(
        "sketch", "Pencil sketch",
        "A graphite pencil portrait sketch on cream paper: soft shading, visible construction lines at the edges, "
        "light smudging and no color.",
        place="A graphite pencil landscape sketch on cream paper: soft shading, visible construction lines at the edges, light smudging and no color.",
    ),
    Style(
        "anime", "Anime",
        "Japanese anime character art, a flat 2D drawing and clearly not realistic: clean fine linework, large "
        "expressive eyes, a tiny simplified nose and mouth, smooth skin with no pores or wrinkles, cel shading with "
        "soft gradients, vivid color and glossy, detailed hair.",
        place="Japanese anime background art, a flat 2D painted scene and clearly not realistic: clean fine linework, richly painted skies and foliage, cel-style shading with soft gradients, vivid color and a soft glow of light.",
    ),
    Style(
        "illustration", "Fantasy novel illustration",
        "A classic fantasy novel cover painting in oil, soft focus at the edges and a soft glow: a gentle painterly "
        "finish with visible brushwork, a warm golden palette, romantic dramatic lighting, and a slightly dreamy, "
        "idealized look, like a printed book jacket.",
        place="A classic fantasy novel cover painting of a landscape in oil, soft focus at the edges and a soft glow: a gentle painterly finish with visible brushwork, a warm golden palette, romantic dramatic lighting, and a slightly dreamy, idealized look, like a printed book jacket.",
    ),
)
BY_ID = {s.id: s for s in STYLES}

# The style each ruleset gets when the player does not choose one. The last four styles belong to no ruleset.
RULESET_STYLE: dict[str, str] = {
    "odnd": "ink",
    "adnd1e": "ink",
    "basic": "gouache",
    "becmi": "gouache",
    "adnd2e": "moody",
    "dnd3e": "comic",
    "dnd35e": "comic",
    "dnd4e": "vivid",
    "dnd5e": "modern",
    "dnd55e": "modern",
    "pf1e": "detailed",
    "pf2e": "clean",
}
assert set(RULESET_STYLE) == {r.id for r in RULESETS} and set(RULESET_STYLE.values()) <= set(BY_ID)


def resolve_style(art_style: str | None, ruleset: str) -> Style | None:
    """The style a game uses: its own choice, else its ruleset's. None when the game has no portraits."""
    if art_style == NO_PORTRAITS:
        return None
    if art_style is None:
        return BY_ID[RULESET_STYLE[ruleset]]
    return BY_ID[art_style]


# Words many people share, so one left alone in a Look ("the marshal") is a role, not a name.
_TITLES = frozenset(
    """lord lady sir dame master mistress mother father brother sister old young king queen prince princess marshal
    captain reeve gaffer goodwife goodman bargewife saltwife sailmaker harbormaster washmistress boilerman sexton
    cooper the of""".split()
)


def scrub_name(text: str, names: list[str], subject: str = "the character") -> str:
    """Replace a character's name with "the character", so a famous name cannot pull a face toward a real person or a
    franchise (docs/PORTRAITS.md 7). Whole names first, then each word of them that is not a shared title. For a place
    (`subject` "the place") only the whole names are replaced: the words of a place's name are ordinary words ("quarry",
    "gate") that the description needs."""
    variants = sorted({n.strip() for n in names if n.strip()}, key=len, reverse=True)
    words = set()
    if subject == "the character":
        words = {w for n in variants for w in re.findall(r"[\w'-]+", n) if len(w) >= 3 and w.lower() not in _TITLES}
    for item in [*variants, *sorted(words, key=len, reverse=True)]:
        article = r"(?:the\s+)?" if subject != "the character" else ""  # "the Old Quarry" -> "the place"
        text = re.sub(rf"(?<!\w){article}{re.escape(item)}(?!\w)", subject, text, flags=re.I)
    text = re.sub(rf"(?<!\w)(?:{subject})(?:\s+{subject})+", subject, text)
    capital = subject[0].upper() + subject[1:]
    return re.sub(rf"(^|[.!?]\s+){subject}", lambda m: m.group(1) + capital, text)


def _tag_line(look: Look, keys: tuple[str, ...] = ("ancestry", "age", "gender", "build")) -> str:
    parts = []
    for key in keys:
        value = look.tags.get(key)
        if isinstance(value, str) and value and value != "other":
            parts.append(value)
    return ", ".join(parts)


def build_prompt(look: Look, style: Style, names: list[str], *, softened: bool = False) -> str:
    """The whole prompt: the style, the framing, then the character. Never the name, facts or anything but the Look
    (`names` are the character's name and aliases, which are taken out of the Look's text).

    `softened` is the retry after a refusal: only the tags and the first sentence of the description."""
    tags = _tag_line(look)
    description = scrub_name(" ".join(look.description.split()), names)
    summary = scrub_name(look.summary.strip(), names)
    if softened:
        description = description.split(". ")[0].rstrip(".") + "."
    character = f"The character: {summary} "
    if tags:
        character += f"({tags}). "
    head = f"{style.direction}\n\n{FRAMING}\n\n"
    body = character + description
    room = MAX_PROMPT_CHARS - len(head)
    if len(body) > room:  # drop the tags, then cut the description at a sentence end
        body = f"The character: {summary} {description}"
        if len(body) > room:
            body = body[:room].rsplit(". ", 1)[0].rstrip(".") + "."
    return f"{head}{body}\n\nRender all of this strictly in the style described first: {style.name.lower()}."


def build_place_prompt(look: Look, style: Style, names: list[str]) -> str:
    """The prompt for a view of a place: the style (its place variant), the framing of a view, the place and a closing
    reminder (docs/PLACES.md 8.2). Never the name, and nothing but the place's Look."""
    tags = _tag_line(look, ("scale", "setting", "climate"))
    summary = scrub_name(look.summary.strip(), names, "the place")
    description = scrub_name(" ".join(look.description.split()), names, "the place")
    head = f"{style.direction_for('place')}\n\n{PLACE_FRAMING}\n\n"
    body = f"The place: {summary} " + (f"({tags}). " if tags else "") + description
    room = MAX_PROMPT_CHARS - len(head)
    if len(body) > room:
        body = f"The place: {summary} {description}"
        if len(body) > room:
            body = body[:room].rsplit(". ", 1)[0].rstrip(".") + "."
    return f"{head}{body}\n\nRender all of this strictly in the style described first: {style.name.lower()}."


def image_id(model: str, size: str, style: Style, prompt: str, quality: str | None = None) -> str:
    """The id of the file this input makes: the same input always gives the same id (docs/PORTRAITS.md 6.3)."""
    key = "\n".join((model, size, quality or "", style.id, prompt))
    return "p_" + hashlib.sha256(key.encode()).hexdigest()[:16]


def catalog() -> list[dict[str, Any]]:
    return [{"id": s.id, "name": s.name} for s in STYLES]
