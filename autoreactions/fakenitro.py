import re
from typing import Iterable, List, Tuple
from urllib.parse import parse_qs, urlparse

import discord


FAKENITRO_MARKDOWN_RE = re.compile(
    r"^\[([^\]]+)\]\((https?://(?:cdn\.discordapp\.com|media\.discordapp\.net)/emojis/(\d+)\.(?:png|webp|gif)(?:\?[^)]*)?)\)$",
    re.IGNORECASE,
)
FAKENITRO_URL_RE = re.compile(
    r"^(https?://(?:cdn\.discordapp\.com|media\.discordapp\.net)/emojis/(\d+)\.(?:png|webp|gif)(?:\?\S*)?)$",
    re.IGNORECASE,
)
PREFIX_ONLY = {"normal:", "n:", "burst:", "super:", "s:"}


def _fake_nitro_to_custom_emoji(raw: str) -> str:
    """Converte il formato FakeNitro CDN in una custom emoji Discord."""
    value = raw.strip()
    label = None
    url = None
    emoji_id = None

    match = FAKENITRO_MARKDOWN_RE.match(value)
    if match:
        label = match.group(1).strip()
        url = match.group(2)
        emoji_id = match.group(3)
    else:
        match = FAKENITRO_URL_RE.match(value)
        if not match:
            return value
        url = match.group(1)
        emoji_id = match.group(2)

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    name = label or (query.get("name", [None])[0]) or f"emoji_{emoji_id}"
    name = re.sub(r"[^A-Za-z0-9_]", "_", name).strip("_") or f"emoji_{emoji_id}"
    animated = (
        parsed.path.lower().endswith(".gif")
        or query.get("animated", [""])[0].lower() in {"1", "true", "yes"}
    )
    return f"<{'a' if animated else ''}:{name}:{emoji_id}>"


def _merge_reaction_args(reactions: Iterable[str]) -> List[str]:
    """Ricompone `burst:` + emoji quando FakeNitro li divide in due argomenti."""
    values = list(reactions)
    merged = []
    index = 0
    while index < len(values):
        current = values[index].strip()
        if current.lower() in PREFIX_ONLY and index + 1 < len(values):
            merged.append(current + values[index + 1].strip())
            index += 2
            continue
        merged.append(current)
        index += 1
    return merged


def patch_autoreactions(cls):
    original_split = cls._split_reaction_spec

    def split_reaction_spec(raw: str) -> Tuple[str, str]:
        reaction_type, emoji = original_split(raw)
        return reaction_type, _fake_nitro_to_custom_emoji(emoji)

    cls._split_reaction_spec = staticmethod(split_reaction_spec)

    async def validate_reaction_spec(self, guild: discord.Guild, raw: str):
        reaction_type, emoji = self._split_reaction_spec(raw)
        if reaction_type not in {"normal", "burst"}:
            return False, "Tipo non valido. Usa `normal:` oppure `burst:`."
        if not emoji:
            return False, "Emoji vuota."

        # Per le emoji FakeNitro non blocchiamo in base alla cache locale:
        # proviamo direttamente con l'ID reale estratto dal CDN e lasciamo a
        # Discord la decisione sull'accesso all'emoji.
        return True, None

    cls._validate_reaction_spec = validate_reaction_spec

    async def validate_many(self, guild, reactions):
        normalized = []
        for reaction in _merge_reaction_args(reactions):
            ok, error = await self._validate_reaction_spec(guild, reaction)
            if not ok:
                return None, f"`{reaction}`: {error}"
            normalized.append(self._normalize_spec(reaction))
        return normalized, None

    cls._validate_many = validate_many

    # `test` riceve *args direttamente dal parser comandi, quindi va ricomposto
    # qui prima di tentare le reazioni.
    command = getattr(cls, "autoreact_test", None)
    if command is not None and hasattr(command, "callback"):
        async def test_callback(self, ctx, *reactions: str):
            prepared = _merge_reaction_args(reactions)
            if not prepared:
                await ctx.send("❌ Esempio: `.ar test normal:👍 burst:🔥`.")
                return

            results = []
            for raw in prepared:
                ok, error = await self._validate_reaction_spec(ctx.guild, raw)
                if not ok:
                    results.append(f"❌ `{raw}`: {error}")
                    continue

                reaction_type, emoji = self._split_reaction_spec(raw)
                if reaction_type == "burst":
                    success, detail = await self._add_burst_reaction(ctx.message, emoji)
                else:
                    success, detail = await self._add_normal_reaction(ctx.message, emoji)

                normalized = self._normalize_spec(raw)
                results.append(f"{'✅' if success else '❌'} `{normalized}` — {detail}")

            await ctx.send("**Test AutoReactions**\n" + "\n".join(results))

        command.callback = test_callback

    return cls
